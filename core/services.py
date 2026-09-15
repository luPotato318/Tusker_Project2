import base64
import hashlib
import json

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.db.models import Prefetch

from .models import AuditLog, ChallengeSubmission, User


def _cipher():
    configured = getattr(settings, "SAFE_REPORT_ENCRYPTION_KEY", "")
    if configured:
        key = configured.encode()
    else:
        key = base64.urlsafe_b64encode(hashlib.sha256(settings.SECRET_KEY.encode()).digest())
    return Fernet(key)


def encrypt_sensitive(value):
    if not value:
        return ""
    return "enc:v1:" + _cipher().encrypt(value.encode()).decode()


def decrypt_sensitive(value):
    if not value or not value.startswith("enc:v1:"):
        return value or ""
    try:
        return _cipher().decrypt(value[7:].encode()).decode()
    except (InvalidToken, ValueError):
        return "[conteúdo indisponível: chave de proteção divergente]"


def client_ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    return forwarded.split(",")[0].strip() or request.META.get("REMOTE_ADDR")


def audit(request, action, instance=None, details=None):
    return AuditLog.objects.create(
        ator=request.user if getattr(request, "user", None) and request.user.is_authenticated else None,
        acao=action,
        entidade=instance.__class__.__name__ if instance else "Sistema",
        entidade_id=str(getattr(instance, "pk", "")),
        detalhes=details or {},
        ip=client_ip(request),
    )


def employability_score(student):
    """Score transparente de 0–1000: frequência 35%, soft skills 30%, entregas 35%."""
    # Read related objects once so ranked_students can reuse its batched queries.
    attendances = list(student.frequencias.all())
    attendance_ratio = sum(item.presente for item in attendances) / len(attendances) if attendances else 0

    assessments = list(student.avaliacoes_soft_skills.all())
    soft_ratio = (
        sum(item.comunicacao + item.proatividade + item.trabalho_equipe for item in assessments)
        / (len(assessments) * 15)
        if assessments else 0
    )

    deliveries = student.entregas_desafios.all()
    if "entregas_desafios" not in getattr(student, "_prefetched_objects_cache", {}):
        deliveries = deliveries.select_related("desafio")
    deliveries = list(deliveries)
    awarded = sum(item.pontos_atribuidos for item in deliveries)
    possible = sum(item.desafio.pontos for item in deliveries)
    delivery_ratio = min(1, awarded / possible) if possible else 0

    components = {
        "frequencia": round(attendance_ratio * 350),
        "soft_skills": round(soft_ratio * 300),
        "entregas": round(delivery_ratio * 350),
    }
    score = min(1000, sum(components.values()))
    if score >= 800:
        level = "Pronto para oportunidades"
    elif score >= 550:
        level = "Em aceleração"
    elif score >= 300:
        level = "Em desenvolvimento"
    else:
        level = "Início da jornada"
    return {"score": score, "level": level, "components": components}


def ranked_students(queryset=None):
    students = queryset if queryset is not None else User.objects.filter(perfil_acesso=User.Role.STUDENT)
    students = students.select_related("escola", "turma").prefetch_related(
        "frequencias",
        "avaliacoes_soft_skills",
        Prefetch("entregas_desafios", queryset=ChallengeSubmission.objects.select_related("desafio")),
    )
    ranking = [{"student": student, **employability_score(student)} for student in students]
    ranking.sort(key=lambda item: (-item["score"], item["student"].nome.lower()))
    for position, item in enumerate(ranking, start=1):
        item["position"] = position
    return ranking


def json_report_payload(students):
    return [
        {
            "codigo": item["student"].talent_code,
            "nome": item["student"].nome,
            "escola": item["student"].escola.nome if item["student"].escola else "",
            "turma": item["student"].turma.nome if item["student"].turma else "",
            "score": item["score"],
            "nivel": item["level"],
            **item["components"],
        }
        for item in ranked_students(students)
    ]
