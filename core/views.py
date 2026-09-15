import json
import secrets
from io import BytesIO
from xml.sax.saxutils import escape

import qrcode
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models.deletion import ProtectedError
from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.conf import settings

from .forms import (
    AdminUserForm,
    AdminLoginForm,
    ChallengeForm,
    ChallengeSubmissionForm,
    JobOpportunityForm,
    ProjectForm,
    RegistrationForm,
    SafeReportStatusForm,
    SoftSkillAssessmentForm,
    StudentLoginForm,
    SubmissionReviewForm,
    WorkshopForm,
)
from .media_engine import get_contextual_image
from .models import (
    AuditLog,
    Certificate,
    ChallengeSubmission,
    ChatMessage,
    ChatSession,
    JobApplication,
    JobOpportunity,
    PracticalChallenge,
    SafeReport,
    SoftSkillAssessment,
    StudentProject,
    User,
    Workshop,
    WorkshopEnrollment,
)
from .rbac import role_required
from .risk import attendance_risk
from .services import (
    audit,
    decrypt_sensitive,
    employability_score,
    encrypt_sensitive,
    json_report_payload,
    ranked_students,
)
from .tutor import tutor_reply


def _portal_name(user):
    return {
        User.Role.STUDENT: "dashboard",
        User.Role.TEACHER: "teacher_dashboard",
        User.Role.ADMIN: "admin_dashboard",
        User.Role.RECRUITER: "recruiter_dashboard",
    }.get(user.perfil_acesso, "home")


def _students_for_staff(user):
    students = User.objects.filter(perfil_acesso=User.Role.STUDENT).select_related("escola", "turma")
    if user.is_superuser or user.perfil_acesso == User.Role.ADMIN:
        return students
    class_ids = user.turmas_docentes.values_list("id", flat=True)
    scope = Q(turma_id__in=class_ids)
    if user.escola_id:
        scope |= Q(escola_id=user.escola_id, turma__isnull=True)
    return students.filter(scope).distinct()


def _ensure_student_scope(actor, student):
    if actor.is_superuser or actor.perfil_acesso == User.Role.ADMIN:
        return
    if not _students_for_staff(actor).filter(pk=student.pk).exists():
        raise PermissionDenied("Aluno fora do seu escopo escolar.")


def home(request):
    areas = [area[0] for area in Workshop.AREAS]
    featured_projects = StudentProject.objects.filter(publico=True).select_related("aluno").order_by("-destaque", "-updated_at")[:6]
    workshops = list(Workshop.objects.filter(status=Workshop.Status.PUBLISHED, data__gte=timezone.now()).order_by("data")[:3])
    for workshop in workshops:
        workshop.image_url = get_contextual_image(workshop.imagem_query or workshop.area)
    return render(request, "core/index.html", {
        "areas": areas,
        "featured_projects": featured_projects,
        "workshops": workshops,
        "hero_image": get_contextual_image("jovens estudantes carreira tecnologia liderança"),
        "total_alunos": User.objects.filter(perfil_acesso=User.Role.STUDENT).count(),
        "total_projetos": StudentProject.objects.count(),
        "total_certificados": Certificate.objects.count(),
    })


def courses_view(request):
    courses = Workshop.objects.filter(status=Workshop.Status.PUBLISHED, data__gte=timezone.now()).select_related("mentor", "escola")
    if request.user.is_authenticated and request.user.perfil_acesso == User.Role.STUDENT:
        courses = courses.filter(Q(escola__isnull=True) | Q(escola=request.user.escola))
    area = request.GET.get("area", "").strip()
    query = request.GET.get("q", "").strip()
    modality = request.GET.get("modalidade", "").strip()
    if area:
        courses = courses.filter(area=area)
    if modality:
        courses = courses.filter(modalidade=modality)
    if query:
        courses = courses.filter(Q(titulo__icontains=query) | Q(descricao__icontains=query) | Q(area__icontains=query))
    paginator = Paginator(courses.order_by("data", "pk").prefetch_related("inscricoes"), 12)
    page_obj = paginator.get_page(request.GET.get("page"))
    courses = list(page_obj.object_list)
    pagination_params = request.GET.copy()
    pagination_params.pop("page", None)
    for course in courses:
        course.image_url = get_contextual_image(course.imagem_query or course.area)
    enrollment_ids = set()
    if request.user.is_authenticated and request.user.perfil_acesso == User.Role.STUDENT:
        enrollment_ids = set(request.user.inscricoes_oficinas.values_list("workshop_id", flat=True))
    return render(request, "core/courses.html", {
        "courses": courses,
        "page_obj": page_obj,
        "paginator": paginator,
        "pagination_query": pagination_params.urlencode(),
        "areas": [item[0] for item in Workshop.AREAS],
        "modalities": Workshop.Modality.choices,
        "selected_area": area,
        "selected_modality": modality,
        "query": query,
        "user_enrollments": enrollment_ids,
    })


def showcase_view(request):
    projects = StudentProject.objects.filter(publico=True).select_related("aluno").order_by("-destaque", "-updated_at")
    return render(request, "core/showcase.html", {"projects": projects, "areas": [area[0] for area in Workshop.AREAS]})


def register_view(request):
    form = RegistrationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        messages.success(request, f"Bem-vindo ao PIEM, {user.nome}.")
        return redirect(_portal_name(user))
    return render(request, "core/auth_aluno.html", {"form": form, "title": "Criar conta", "is_register": True})


def login_aluno_view(request):
    if request.user.is_authenticated:
        return redirect(_portal_name(request.user))
    form = StudentLoginForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.cleaned_data["user"]
        login(request, user)
        messages.success(request, f"Bem-vindo de volta, {user.nome}.")
        return redirect(_portal_name(user))
    return render(request, "core/auth_aluno.html", {"form": form, "title": "Acesso aos portais", "is_register": False})


def login_admin_view(request):
    if request.user.is_authenticated and request.user.perfil_acesso == User.Role.ADMIN:
        return redirect("admin_dashboard")
    form = AdminLoginForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.cleaned_data["user"]
        login(request, user)
        return redirect("admin_dashboard")
    return render(request, "core/auth_admin.html", {"form": form, "title": "Acesso administrativo PIEM"})


@require_POST
def logout_view(request):
    logout(request)
    messages.info(request, "Sua sessão foi encerrada com segurança.")
    return redirect("home")


@login_required
def dashboard(request):
    if request.user.perfil_acesso != User.Role.STUDENT:
        return redirect(_portal_name(request.user))
    user = request.user
    projects = user.projetos.all().order_by("-updated_at")
    workshops = Workshop.objects.filter(
        Q(escola__isnull=True) | Q(escola=user.escola),
        status=Workshop.Status.PUBLISHED,
        data__gte=timezone.now(),
    ).order_by("data")[:6]
    enrollment_ids = set(user.inscricoes_oficinas.values_list("workshop_id", flat=True))
    challenge_query = PracticalChallenge.objects.filter(ativo=True).filter(Q(turma__isnull=True) | Q(turma=user.turma))
    challenges = list(challenge_query.select_related("turma")[:8])
    submissions = {item.desafio_id: item for item in user.entregas_desafios.select_related("desafio")}
    for challenge in challenges:
        challenge.student_submission = submissions.get(challenge.id)
    ranking = ranked_students(User.objects.filter(perfil_acesso=User.Role.STUDENT, escola=user.escola))
    own_rank = next((item for item in ranking if item["student"].pk == user.pk), None)
    jobs = JobOpportunity.objects.filter(ativa=True).filter(
        Q(escola__isnull=True) | Q(escola=user.escola),
        Q(encerra_em__isnull=True) | Q(encerra_em__gt=timezone.now()),
    )[:6]
    session = user.sessoes_tutor.order_by("-atualizada_em").first()
    return render(request, "core/dashboard.html", {
        "risk": attendance_risk(user.frequencias),
        "score": employability_score(user),
        "own_rank": own_rank,
        "projects": projects,
        "workshops": workshops,
        "user_enrollments": enrollment_ids,
        "challenges": challenges,
        "jobs": jobs,
        "applications": {item.vaga_id: item for item in user.candidaturas.all()},
        "chat_history": session.mensagens.all() if session else [],
        "chat_session_id": session.pk if session else None,
    })


@role_required(User.Role.TEACHER, User.Role.ADMIN)
def teacher_dashboard(request):
    students = _students_for_staff(request.user)
    ranking = ranked_students(students)
    for item in ranking:
        item["risk"] = attendance_risk(item["student"].frequencias)
    class_ids = request.user.turmas_docentes.values_list("id", flat=True)
    submissions = ChallengeSubmission.objects.select_related("aluno", "desafio").filter(status=ChallengeSubmission.Status.PENDING)
    if request.user.perfil_acesso == User.Role.TEACHER and not request.user.is_superuser:
        submissions = submissions.filter(desafio__turma_id__in=class_ids)
    return render(request, "core/teacher_dashboard.html", {
        "ranking": ranking,
        "pending_submissions": submissions,
        "challenges": request.user.desafios_criados.all()[:8],
        "challenge_form": ChallengeForm(teacher=request.user),
    })


@role_required(User.Role.TEACHER, User.Role.ADMIN)
@require_POST
def challenge_create(request):
    form = ChallengeForm(request.POST, teacher=request.user)
    if form.is_valid():
        challenge = form.save(commit=False)
        challenge.criado_por = request.user
        challenge.save()
        audit(request, "challenge.created", challenge, {"points": challenge.pontos})
        messages.success(request, "Desafio publicado para a turma.")
    else:
        messages.error(request, "Revise os dados do desafio.")
    return redirect("teacher_dashboard")


@role_required(User.Role.STUDENT)
def challenge_submit(request, challenge_id):
    challenge = get_object_or_404(PracticalChallenge, pk=challenge_id, ativo=True)
    if challenge.turma_id and challenge.turma_id != request.user.turma_id:
        raise PermissionDenied("Este desafio pertence a outra turma.")
    submission = ChallengeSubmission.objects.filter(desafio=challenge, aluno=request.user).first()
    if submission and submission.status == ChallengeSubmission.Status.APPROVED:
        messages.info(request, "Esta entrega já foi aprovada.")
        return redirect("dashboard")
    form = ChallengeSubmissionForm(request.POST or None, instance=submission)
    if request.method == "POST" and form.is_valid():
        item = form.save(commit=False)
        item.desafio = challenge
        item.aluno = request.user
        item.status = ChallengeSubmission.Status.PENDING
        item.save()
        audit(request, "submission.sent", item)
        messages.success(request, "Entrega enviada para correção.")
        return redirect("dashboard")
    return render(request, "core/challenge_submit.html", {"challenge": challenge, "form": form})


@role_required(User.Role.TEACHER, User.Role.ADMIN)
def submission_review(request, submission_id):
    submission = get_object_or_404(ChallengeSubmission.objects.select_related("aluno", "desafio"), pk=submission_id)
    _ensure_student_scope(request.user, submission.aluno)
    form = SubmissionReviewForm(request.POST or None, instance=submission)
    if request.method == "POST" and form.is_valid():
        item = form.save(commit=False)
        item.avaliado_por = request.user
        item.avaliado_em = timezone.now()
        item.save()
        audit(request, "submission.reviewed", item, {"status": item.status, "points": item.pontos_atribuidos})
        messages.success(request, "Correção e feedback registrados.")
        return redirect("teacher_dashboard")
    return render(request, "core/submission_review.html", {"submission": submission, "form": form})


@role_required(User.Role.TEACHER, User.Role.ADMIN)
def soft_skill_assess(request, student_id):
    student = get_object_or_404(User, pk=student_id, perfil_acesso=User.Role.STUDENT)
    _ensure_student_scope(request.user, student)
    form = SoftSkillAssessmentForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        assessment = form.save(commit=False)
        assessment.aluno = student
        assessment.avaliador = request.user
        assessment.save()
        audit(request, "soft_skills.assessed", assessment, {"average": assessment.media})
        messages.success(request, "Matriz de soft skills atualizada.")
        return redirect("teacher_dashboard")
    return render(request, "core/soft_skill_form.html", {"student": student, "form": form})


@role_required(User.Role.RECRUITER, User.Role.ADMIN)
def recruiter_dashboard(request):
    students = User.objects.filter(perfil_acesso=User.Role.STUDENT, consentimento_vitrine=True).select_related("escola", "turma")
    if request.user.escola_id:
        students = students.filter(escola=request.user.escola)
    area = request.GET.get("area", "").strip()
    skill = request.GET.get("competencia", "").strip()
    if area:
        students = students.filter(area_interesse__icontains=area)
    if skill:
        students = students.filter(competencias__icontains=skill)
    try:
        min_score = max(0, min(1000, int(request.GET.get("score", 0) or 0)))
    except (TypeError, ValueError):
        min_score = 0
    talents = [item for item in ranked_students(students) if item["score"] >= min_score]
    audit(request, "talent_showcase.accessed", details={"filters": {"area": area, "skill": skill, "score": min_score}})
    jobs = JobOpportunity.objects.filter(publicada_por=request.user) if request.user.perfil_acesso == User.Role.RECRUITER else JobOpportunity.objects.all()
    return render(request, "core/recruiter_dashboard.html", {
        "talents": talents,
        "jobs": jobs,
        "job_form": JobOpportunityForm(actor=request.user),
        "areas": [area[0] for area in Workshop.AREAS],
    })


@role_required(User.Role.RECRUITER, User.Role.ADMIN)
@require_POST
def job_create(request):
    form = JobOpportunityForm(request.POST, actor=request.user)
    if form.is_valid():
        job = form.save(commit=False)
        job.publicada_por = request.user
        if request.user.perfil_acesso == User.Role.RECRUITER:
            job.escola = request.user.escola
        job.save()
        audit(request, "job.created", job)
        messages.success(request, "Vaga publicada para os estudantes elegíveis.")
    else:
        messages.error(request, "Revise os dados da vaga.")
    return redirect("recruiter_dashboard")


@role_required(User.Role.STUDENT)
@require_POST
def job_apply(request, job_id):
    job = get_object_or_404(JobOpportunity, pk=job_id, ativa=True)
    if job.escola_id and job.escola_id != request.user.escola_id:
        raise PermissionDenied("Esta vaga está vinculada a outra escola.")
    if job.encerra_em and job.encerra_em <= timezone.now():
        messages.error(request, "O prazo de candidatura para esta vaga foi encerrado.")
        return redirect("dashboard")
    application, created = JobApplication.objects.get_or_create(
        vaga=job,
        aluno=request.user,
        defaults={"carta_apresentacao": request.POST.get("carta_apresentacao", "")[:4000]},
    )
    audit(request, "application.created" if created else "application.duplicate", application)
    messages.success(request, "Candidatura enviada." if created else "Sua candidatura já estava registrada.")
    return redirect("dashboard")


@role_required(User.Role.ADMIN)
def admin_dashboard_view(request):
    all_users = User.objects.select_related("escola", "turma").order_by("-created_at")
    users = all_users
    user_query = request.GET.get("usuario", "").strip()
    selected_role = request.GET.get("papel", "").strip()
    if user_query:
        users = users.filter(Q(nome__icontains=user_query) | Q(identifier__icontains=user_query) | Q(email__icontains=user_query))
    if selected_role:
        users = users.filter(perfil_acesso=selected_role)
    course_query = request.GET.get("curso", "").strip()
    selected_course_status = request.GET.get("status_curso", "").strip()
    workshops = Workshop.objects.select_related("mentor", "escola").prefetch_related("inscricoes").order_by("-data")
    if course_query:
        workshops = workshops.filter(Q(titulo__icontains=course_query) | Q(area__icontains=course_query))
    if selected_course_status:
        workshops = workshops.filter(status=selected_course_status)
    reports = []
    for item in SafeReport.objects.select_related("escola").order_by("-criado_em"):
        reports.append({"item": item, "mensagem": decrypt_sensitive(item.mensagem), "contato": decrypt_sensitive(item.contato_seguro)})
    metrics = {
        "total_users": all_users.count(),
        "total_alunos": all_users.filter(perfil_acesso=User.Role.STUDENT).count(),
        "total_teachers": all_users.filter(perfil_acesso=User.Role.TEACHER).count(),
        "total_recruiters": all_users.filter(perfil_acesso=User.Role.RECRUITER).count(),
        "active_users": all_users.filter(is_active=True).count(),
        "users_without_email": all_users.filter(email="").count(),
        "total_projects": StudentProject.objects.count(),
        "total_workshops": Workshop.objects.count(),
        "pending_reports": SafeReport.objects.exclude(status=SafeReport.Status.RESOLVED).count(),
    }
    audit(request, "admin.dashboard.accessed")
    return render(request, "core/admin_dashboard.html", {
        "metrics": metrics,
        "users_list": users,
        "workshops_list": workshops,
        "safe_reports": reports,
        "audit_logs": AuditLog.objects.select_related("ator")[:20],
        "user_roles": User.Role.choices,
        "workshop_statuses": Workshop.Status.choices,
        "selected_role": selected_role,
        "selected_course_status": selected_course_status,
        "user_query": user_query,
        "course_query": course_query,
    })


@role_required(User.Role.ADMIN)
def admin_workshop_create(request):
    form = WorkshopForm(request.POST or None, actor=request.user)
    if request.method == "POST" and form.is_valid():
        workshop = form.save(commit=False)
        if not workshop.mentor_id:
            workshop.mentor = request.user
        workshop.save()
        audit(request, "workshop.created", workshop)
        messages.success(request, "Curso/oficina cadastrado e pronto para gerenciamento.")
        return redirect("admin_workshop_detail", workshop_id=workshop.pk)
    return render(request, "core/admin_record_form.html", {
        "form": form,
        "title": "Cadastrar curso ou oficina",
        "eyebrow": "Catálogo de capacitações",
        "submit_label": "Salvar curso",
        "cancel_url": reverse("admin_dashboard") + "#cursos",
    })


@role_required(User.Role.ADMIN)
def admin_workshop_edit(request, workshop_id):
    workshop = get_object_or_404(Workshop, pk=workshop_id)
    form = WorkshopForm(request.POST or None, instance=workshop, actor=request.user)
    if request.method == "POST" and form.is_valid():
        workshop = form.save()
        audit(request, "workshop.updated", workshop, {"status": workshop.status})
        messages.success(request, "Dados do curso atualizados.")
        return redirect("admin_workshop_detail", workshop_id=workshop.pk)
    return render(request, "core/admin_record_form.html", {
        "form": form,
        "title": f"Editar {workshop.titulo}",
        "eyebrow": "Gestão de curso",
        "submit_label": "Salvar alterações",
        "cancel_url": reverse("admin_workshop_detail", args=[workshop.pk]),
    })


@role_required(User.Role.ADMIN)
def admin_workshop_detail(request, workshop_id):
    workshop = get_object_or_404(Workshop.objects.select_related("mentor", "escola"), pk=workshop_id)
    enrollments = workshop.inscricoes.select_related("user", "user__escola", "user__turma").order_by("user__nome")
    return render(request, "core/admin_workshop_detail.html", {"workshop": workshop, "enrollments": enrollments})


@role_required(User.Role.ADMIN)
@require_POST
def admin_workshop_delete(request, workshop_id):
    workshop = get_object_or_404(Workshop, pk=workshop_id)
    if workshop.inscricoes.exists():
        workshop.status = Workshop.Status.CANCELLED
        workshop.save(update_fields=["status"])
        audit(request, "workshop.cancelled", workshop, {"reason": "delete_blocked_by_enrollments"})
        messages.warning(request, "O curso possui inscritos e foi cancelado para preservar o histórico. Remova as inscrições antes de excluir.")
    else:
        details = {"id": workshop.pk, "title": workshop.titulo}
        audit(request, "workshop.deleted", details=details)
        workshop.delete()
        messages.success(request, "Curso excluído com segurança.")
    return redirect(reverse("admin_dashboard") + "#cursos")


@role_required(User.Role.ADMIN)
def admin_user_create(request):
    form = AdminUserForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        account = form.save()
        audit(request, "user.created", account, {"role": account.perfil_acesso})
        messages.success(request, f"Usuário {account.nome} cadastrado. O e-mail já pode ser usado no login.")
        return redirect(reverse("admin_dashboard") + "#usuarios")
    return render(request, "core/admin_record_form.html", {
        "form": form,
        "title": "Adicionar usuário",
        "eyebrow": "Acesso e e-mail",
        "submit_label": "Criar usuário",
        "cancel_url": reverse("admin_dashboard") + "#usuarios",
    })


@role_required(User.Role.ADMIN)
def admin_user_edit(request, user_id):
    account = get_object_or_404(User, pk=user_id)
    form = AdminUserForm(request.POST or None, instance=account)
    if request.method == "POST" and form.is_valid():
        if account == request.user and (
            form.cleaned_data["perfil_acesso"] != User.Role.ADMIN or not form.cleaned_data["is_active"]
        ):
            form.add_error(None, "Você não pode remover o próprio acesso administrativo nem desativar sua conta.")
        else:
            account = form.save()
            audit(request, "user.updated", account, {"role": account.perfil_acesso, "active": account.is_active})
            messages.success(request, "Cadastro, e-mail e permissões atualizados.")
            return redirect(reverse("admin_dashboard") + "#usuarios")
    return render(request, "core/admin_record_form.html", {
        "form": form,
        "title": f"Editar {account.nome}",
        "eyebrow": "Gestão de usuário",
        "submit_label": "Salvar usuário",
        "cancel_url": reverse("admin_dashboard") + "#usuarios",
    })


@role_required(User.Role.ADMIN)
@require_POST
def admin_user_toggle_active(request, user_id):
    account = get_object_or_404(User, pk=user_id)
    if account == request.user or account.is_superuser:
        messages.error(request, "Essa conta administrativa protegida não pode ser desativada por este painel.")
    else:
        account.is_active = not account.is_active
        account.save(update_fields=["is_active"])
        audit(request, "user.status_changed", account, {"active": account.is_active})
        messages.success(request, "Usuário reativado." if account.is_active else "Usuário desativado sem apagar seu histórico.")
    return redirect(reverse("admin_dashboard") + "#usuarios")


@role_required(User.Role.ADMIN)
@require_POST
def admin_user_delete(request, user_id):
    account = get_object_or_404(User, pk=user_id)
    if account == request.user or account.is_superuser:
        messages.error(request, "A conta administrativa em uso ou um superusuário não pode ser excluído.")
        return redirect(reverse("admin_dashboard") + "#usuarios")
    details = {"id": account.pk, "name": account.nome, "role": account.perfil_acesso}
    try:
        account.delete()
    except ProtectedError:
        messages.error(request, "Este usuário possui registros protegidos. Desative a conta para preservar a auditoria.")
    else:
        audit(request, "user.deleted", details=details)
        messages.success(request, "Usuário excluído.")
    return redirect(reverse("admin_dashboard") + "#usuarios")


@role_required(User.Role.ADMIN)
@require_POST
def admin_safe_report_toggle(request, report_id):
    report = get_object_or_404(SafeReport, id=report_id)
    form = SafeReportStatusForm(request.POST, instance=report)
    if not form.is_valid():
        messages.error(request, "Selecione um status válido para o protocolo.")
        return redirect(reverse("admin_dashboard") + "#acolhimento")
    report = form.save(commit=False)
    report.tratado = report.status == SafeReport.Status.RESOLVED
    report.save(update_fields=["status", "tratado"])
    audit(request, "safe_report.status_changed", report, {"status": report.status})
    messages.success(request, "Status do protocolo atualizado.")
    return redirect(reverse("admin_dashboard") + "#acolhimento")


@role_required(User.Role.STUDENT)
@require_POST
def workshop_enroll(request, workshop_id):
    with transaction.atomic():
        workshop = get_object_or_404(Workshop.objects.select_for_update(), id=workshop_id)
        if workshop.escola_id and workshop.escola_id != request.user.escola_id:
            raise PermissionDenied("Oficina indisponível para sua escola.")
        enrollment = WorkshopEnrollment.objects.filter(user=request.user, workshop=workshop).first()
        if enrollment:
            enrollment.delete()
            audit(request, "workshop.enrollment_cancelled", workshop)
            messages.success(request, "Inscrição cancelada.")
        elif not workshop.aceita_inscricoes:
            messages.error(request, "As inscrições para este curso estão encerradas ou sem vagas.")
        else:
            WorkshopEnrollment.objects.create(user=request.user, workshop=workshop)
            audit(request, "workshop.enrolled", workshop)
            messages.success(request, "Inscrição confirmada.")
    allowed_destinations = {reverse("dashboard"), reverse("courses")}
    destination = request.POST.get("next", "")
    return redirect(destination if destination in allowed_destinations else reverse("dashboard"))


@role_required(User.Role.STUDENT)
def project_create(request):
    form = ProjectForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        project = form.save(commit=False)
        project.aluno = request.user
        project.save()
        if project.status == StudentProject.Status.CONCLUIDO:
            Certificate.objects.get_or_create(aluno=request.user, projeto=project)
        audit(request, "project.created", project)
        messages.success(request, "Projeto registrado no portfólio.")
        return redirect("dashboard")
    return render(request, "core/project_form.html", {"form": form})


@role_required(User.Role.STUDENT)
def project_edit(request, project_id):
    project = get_object_or_404(StudentProject, pk=project_id, aluno=request.user)
    form = ProjectForm(request.POST or None, instance=project)
    if request.method == "POST" and form.is_valid():
        project = form.save()
        if project.status == StudentProject.Status.CONCLUIDO:
            Certificate.objects.get_or_create(aluno=request.user, projeto=project)
        audit(request, "project.updated", project)
        messages.success(request, "Projeto atualizado.")
        return redirect("dashboard")
    return render(request, "core/project_form.html", {"form": form, "project": project})


@role_required(User.Role.STUDENT)
@require_POST
def project_delete(request, project_id):
    project = get_object_or_404(StudentProject, pk=project_id, aluno=request.user)
    details = {"id": project.pk, "title": project.titulo}
    project.delete()
    audit(request, "project.deleted", details=details)
    messages.success(request, "Projeto removido do portfólio.")
    return redirect("dashboard")


def certificate_verify(request, code):
    certificate = get_object_or_404(Certificate.objects.select_related("aluno", "projeto"), codigo=code)
    return render(request, "core/certificate.html", {"certificate": certificate})


def certificate_qr(request, code):
    url = request.build_absolute_uri(reverse("certificate_verify", args=[code]))
    image = qrcode.make(url)
    buffer = BytesIO()
    image.save(buffer)
    return HttpResponse(buffer.getvalue(), content_type="image/png")


@require_POST
def safe_report(request):
    message = request.POST.get("mensagem", "").strip()
    if not message:
        messages.error(request, "Descreva brevemente a situação.")
        return redirect("home")
    report = SafeReport.objects.create(
        categoria=request.POST.get("categoria", "Acolhimento")[:80],
        mensagem=encrypt_sensitive(message),
        contato_seguro=encrypt_sensitive(request.POST.get("contato", "").strip()),
        escola=request.user.escola if request.user.is_authenticated else None,
    )
    messages.success(request, f"Relato protegido recebido. Protocolo: {str(report.protocolo)[:8].upper()}.")
    return redirect("home")


def _tutor_request_payload(request):
    payload = json.loads(request.body or "{}")
    if not isinstance(payload, dict):
        raise ValueError("O corpo da requisição deve ser um objeto JSON.")
    text = payload.get("mensagem")
    if not isinstance(text, str) or not text.strip() or len(text) > 4000:
        raise ValueError("Informe uma mensagem de até 4000 caracteres.")
    return payload, text.strip()


@role_required(User.Role.STUDENT)
@require_POST
def tutor_api(request):
    try:
        payload, text = _tutor_request_payload(request)
        session_id = payload.get("session_id")
        if session_id is not None and (type(session_id) is not int or not 0 < session_id <= 9223372036854775807):
            raise ValueError("Sessão inválida.")
    except (ValueError, TypeError):
        return JsonResponse({"status": "erro", "resposta_tutor": "Informe uma mensagem válida de até 4000 caracteres."}, status=400)

    session = request.user.sessoes_tutor.filter(pk=session_id).first() if session_id is not None else None
    if session_id is not None and session is None:
        return JsonResponse({"status": "erro", "resposta_tutor": "Conversa não encontrada. Atualize a página para continuar."}, status=404)

    reply = tutor_reply(text, request.user.perfil_acesso, request.user.area_interesse, request.user)
    with transaction.atomic():
        if session is None:
            session = ChatSession.objects.create(user=request.user, titulo=text[:70])
        ChatMessage.objects.create(session=session, role=ChatMessage.Role.USER, content=text)
        ChatMessage.objects.create(
            session=session,
            role=ChatMessage.Role.ASSISTANT,
            content=reply["texto"],
            provider=reply.get("provider", "local"),
        )
        session.save(update_fields=["atualizada_em"])
    return JsonResponse({"status": "sucesso", "resposta_tutor": reply, "session_id": session.pk})


@csrf_exempt
@require_POST
def php_bridge_tutor_api(request):
    """Integração servidor-servidor autenticada; não cria sessão nem personifica aluno."""
    configured_secret = settings.PHP_BRIDGE_SECRET
    supplied_secret = request.headers.get("X-PIEM-Bridge-Secret", "")
    if not configured_secret:
        return JsonResponse({"status": "erro", "mensagem": "Ponte PHP não configurada."}, status=503)
    if not supplied_secret or not secrets.compare_digest(configured_secret, supplied_secret):
        return JsonResponse({"status": "erro", "mensagem": "Credencial da ponte inválida."}, status=403)
    try:
        payload, text = _tutor_request_payload(request)
        if any(not isinstance(payload[key], str) for key in ("perfil", "area") if key in payload):
            raise ValueError("Perfil e área devem ser textos.")
        reply = tutor_reply(
            text,
            payload.get("perfil", "external")[:24],
            payload.get("area", "Tecnologia da Informação")[:100],
        )
        return JsonResponse({"status": "sucesso", "resposta_tutor": reply})
    except (json.JSONDecodeError, TypeError, ValueError):
        return JsonResponse({"status": "erro", "mensagem": "Payload inválido."}, status=400)


def _resume_token(user):
    return signing.dumps({"user_id": user.pk, "public_id": str(user.public_id)}, salt="piem.resume.v1", compress=True)


@role_required(User.Role.STUDENT)
def resume_pdf(request):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    user = request.user
    token = _resume_token(user)
    verify_url = request.build_absolute_uri(reverse("resume_verify", args=[token]))
    qr_buffer = BytesIO()
    qrcode.make(verify_url).save(qr_buffer, format="PNG")
    qr_buffer.seek(0)
    output = BytesIO()
    doc = SimpleDocTemplate(output, pagesize=A4, rightMargin=42, leftMargin=42, topMargin=42, bottomMargin=42)
    styles = getSampleStyleSheet()
    score = employability_score(user)
    story = [
        Paragraph(escape(user.nome), styles["Title"]),
        Paragraph(escape(f"{user.area_interesse} · {user.talent_code}"), styles["Heading2"]),
        Spacer(1, 10),
        Paragraph(escape(user.biografia or "Estudante do 3º ano em preparação para oportunidades de aprendizagem e estágio."), styles["BodyText"]),
        Spacer(1, 14),
        Table([["Score PIEM", str(score["score"])], ["Nível", score["level"]], ["Competências", Paragraph(escape(", ".join(user.competencies_list) or "Em desenvolvimento"), styles["BodyText"])]], colWidths=[110, 390]),
        Spacer(1, 14),
        Paragraph("Projetos e evidências", styles["Heading2"]),
    ]
    for project in user.projetos.all()[:8]:
        story.append(Paragraph(f"<b>{escape(project.titulo)}</b> — {escape(project.resumo)}", styles["BodyText"]))
        story.append(Spacer(1, 6))
    verification = Table([[Image(qr_buffer, 72, 72), Paragraph(f"Validação digital PIEM<br/>{escape(verify_url)}", styles["BodyText"])]], colWidths=[84, 416])
    verification.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#800020")), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    story.extend([Spacer(1, 18), verification])
    doc.build(story)
    audit(request, "resume.generated", user)
    response = HttpResponse(output.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="curriculo-{user.talent_code.lower()}.pdf"'
    return response


def resume_verify(request, token):
    try:
        payload = signing.loads(token, salt="piem.resume.v1", max_age=60 * 60 * 24 * 365)
        user = User.objects.get(pk=payload["user_id"], public_id=payload["public_id"], perfil_acesso=User.Role.STUDENT)
    except (signing.BadSignature, signing.SignatureExpired, User.DoesNotExist, KeyError):
        user = None
    return render(request, "core/resume_verify.html", {"talent": user, "score": employability_score(user) if user else None})


@role_required(User.Role.ADMIN)
def impact_export(request, format):
    students = User.objects.filter(perfil_acesso=User.Role.STUDENT).select_related("escola", "turma")
    rows = json_report_payload(students)
    audit(request, "impact_report.exported", details={"format": format, "rows": len(rows)})
    if format == "json":
        return JsonResponse({"generated_at": timezone.now().isoformat(), "students": rows}, json_dumps_params={"ensure_ascii": False, "indent": 2})
    if format == "xlsx":
        from openpyxl import Workbook
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Impacto PIEM"
        headers = ["codigo", "nome", "escola", "turma", "score", "nivel", "frequencia", "soft_skills", "entregas"]
        sheet.append(headers)
        for row in rows:
            sheet.append([row[key] for key in headers])
            # Names and school data are text, even when they begin with '='.
            for cell in sheet[sheet.max_row]:
                if isinstance(cell.value, str):
                    cell.data_type = "s"
        output = BytesIO()
        workbook.save(output)
        response = HttpResponse(output.getvalue(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        response["Content-Disposition"] = 'attachment; filename="impacto-piem.xlsx"'
        return response
    if format == "pdf":
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle
        from reportlab.lib import colors
        output = BytesIO()
        doc = SimpleDocTemplate(output, pagesize=landscape(A4), title="Relatório de Impacto PIEM")
        data = [["Código", "Nome", "Escola", "Turma", "Score", "Nível"]]
        data.extend([[row["codigo"], row["nome"], row["escola"], row["turma"], row["score"], row["nivel"]] for row in rows])
        table = Table(data, repeatRows=1)
        table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#800020")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("GRID", (0, 0), (-1, -1), .4, colors.grey), ("FONTSIZE", (0, 0), (-1, -1), 8)]))
        doc.build([table])
        response = HttpResponse(output.getvalue(), content_type="application/pdf")
        response["Content-Disposition"] = 'attachment; filename="impacto-piem.pdf"'
        return response
    return JsonResponse({"error": "Formato inválido"}, status=400)
