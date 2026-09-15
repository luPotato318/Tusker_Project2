import hashlib
import json
import os
from urllib.request import Request, urlopen

from django.db.models import Count, F, Q
from django.utils import timezone

from .models import Workshop


def _system_prompt(role, area):
    return f"""Você é o Tutor PIEM 2.0, mentor de carreira de estudantes do 3º ano.
Perfil atual: {role}. Área de interesse: {area}.
Responda em português do Brasil, com clareza, acolhimento e orientação prática.
Sempre proponha um próximo passo concreto e breve. Não altere notas ou faltas, não forneça
gabaritos e não invente vagas, certificados ou ações executadas. Em risco pessoal, oriente o
Canal Seguro e serviços locais de emergência. Não exponha dados pessoais de outros estudantes."""


def _post_json(url, payload, headers, timeout=18):
    request = Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "User-Agent": "PIEM-Tutor/3.0", **headers},
        method="POST",
    )
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode())


def _openai_reply(message, instructions, user=None):
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        return None
    safety_identifier = hashlib.sha256(str(getattr(user, "public_id", "anonymous")).encode()).hexdigest()[:32]
    payload = {
        "model": os.getenv("OPENAI_MODEL", "gpt-5.6-luna"),
        "instructions": instructions,
        "input": message,
        "max_output_tokens": 650,
        "store": False,
        "safety_identifier": safety_identifier,
    }
    data = _post_json(
        "https://api.openai.com/v1/responses",
        payload,
        {"Authorization": f"Bearer {api_key}"},
    )
    if data.get("output_text"):
        return data["output_text"]
    texts = []
    for item in data.get("output", []):
        for content in item.get("content", []):
            if content.get("type") == "output_text" and content.get("text"):
                texts.append(content["text"])
    return "\n".join(texts) or None


def _gemini_reply(message, instructions, user=None):
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        return None
    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    data = _post_json(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}",
        {
            "system_instruction": {"parts": [{"text": instructions}]},
            "contents": [{"role": "user", "parts": [{"text": message}]}],
            "generationConfig": {"maxOutputTokens": 650, "temperature": 0.5},
        },
        {},
    )
    return data["candidates"][0]["content"]["parts"][0]["text"]


def _anthropic_reply(message, instructions, user=None):
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        return None
    data = _post_json(
        "https://api.anthropic.com/v1/messages",
        {
            "model": os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5"),
            "system": instructions,
            "messages": [{"role": "user", "content": message}],
            "max_tokens": 650,
        },
        {"x-api-key": api_key, "anthropic-version": "2023-06-01"},
    )
    return "\n".join(item["text"] for item in data.get("content", []) if item.get("type") == "text") or None


PROVIDERS = {
    "openai": _openai_reply,
    "gemini": _gemini_reply,
    "anthropic": _anthropic_reply,
}


def tutor_reply(message, role, area, user=None):
    message = (message or "").strip()
    if not message:
        return {"texto": "Escreva sua dúvida ou escolha um atalho para começarmos.", "tipo": "simples", "provider": "local"}

    lower = message.lower()
    if any(word in lower for word in ["gabarito", "abonar falta", "alterar nota", "mudar nota"]):
        return {
            "texto": "Posso ajudar você a estudar e planejar seus próximos passos, mas não altero notas ou faltas nem forneço respostas prontas de avaliações.",
            "tipo": "simples",
            "provider": "local",
        }
    if any(word in lower for word in ["bullying", "violência", "medo", "agressão", "ameaça"]):
        return {
            "texto": "Sinto muito que você esteja passando por isso. Use o Canal Seguro do PIEM para pedir acolhimento. Se houver risco imediato, procure uma pessoa adulta de confiança ou o serviço de emergência local.",
            "tipo": "alerta",
            "provider": "local",
        }
    if any(term in lower for term in ["recomendar_cursos", "recomendar oficinas", "quais cursos", "quais oficinas"]):
        return get_workshop_recommendations(area, user=user)
    if any(term in lower for term in ["tarefa_dia", "gerar tarefa", "desafio prático", "desafio do dia"]):
        return get_daily_task(area)
    if any(term in lower for term in ["ideia_projeto", "ideias de projetos", "sugerir projeto"]):
        return get_project_idea(area)
    if any(term in lower for term in ["simular_entrevista", "treinar entrevista"]):
        return {
            "texto": f"Simulação de entrevista — {area}\n\nConte sobre um projeto ou problema desafiador que você tentou resolver. Explique o contexto, sua ação e o resultado. Depois avaliarei clareza, objetividade e vocabulário técnico.",
            "tipo": "desafio",
            "provider": "local",
        }

    instructions = _system_prompt(role, area)
    order = [name.strip().lower() for name in os.getenv("LLM_PROVIDER_ORDER", "openai,gemini,anthropic").split(",")]
    for provider_name in order:
        provider = PROVIDERS.get(provider_name)
        if not provider:
            continue
        try:
            text = provider(message, instructions, user)
            if text:
                return {"texto": text, "tipo": "tutor", "provider": provider_name}
        except (OSError, ValueError, KeyError, IndexError, TypeError, json.JSONDecodeError):
            continue

    return {
        "texto": f"Dica prática para {area}: escolha uma competência para exercitar hoje, produza uma evidência curta no seu portfólio e peça feedback a um professor. Confira também os desafios e oficinas abertos no painel.",
        "tipo": "tutor",
        "provider": "local",
    }


def get_workshop_recommendations(area, user=None):
    now = timezone.now()
    available = Workshop.objects.filter(
        Q(escola__isnull=True) | Q(escola_id=getattr(user, "escola_id", None)),
        Q(inscricoes_ate__isnull=True) | Q(inscricoes_ate__gte=now),
        status=Workshop.Status.PUBLISHED,
        data__gte=now,
    ).annotate(enrollment_count=Count("inscricoes")).filter(vagas__gt=F("enrollment_count")).order_by("data")
    workshops = list(available.filter(area__icontains=area)[:3])
    if not workshops:
        workshops = list(available[:3])
    if not workshops:
        return {
            "texto": f"Ainda não há oficinas abertas em {area}. Enquanto isso, registre uma evidência de portfólio e converse com seu professor sobre o próximo desafio.",
            "tipo": "recomendacao",
            "provider": "local",
        }
    rows = [f"• {item.titulo} — {timezone.localtime(item.data):%d/%m/%Y %H:%M} ({item.vagas - item.enrollment_count} vagas)" for item in workshops]
    return {"texto": "Oficinas recomendadas:\n\n" + "\n".join(rows), "tipo": "recomendacao", "provider": "local"}


def get_daily_task(area):
    tasks = {
        "Tecnologia da Informação": ["Documente uma funcionalidade", "Crie um teste", "Peça uma revisão"],
        "Engenharia": ["Defina o problema", "Esboce uma solução", "Liste critérios de validação"],
        "Psicologia": ["Resuma um caso", "Pratique escuta ativa", "Registre um aprendizado ético"],
    }.get(area, ["Defina uma meta", "Produza uma evidência", "Peça feedback"])
    checklist = "\n".join(f"[ ] {index}. {task}" for index, task in enumerate(tasks, 1))
    return {"texto": f"Desafio prático do dia — {area}\n\n{checklist}", "tipo": "tarefa", "provider": "local"}


def get_project_idea(area):
    idea = {
        "Tecnologia da Informação": "Plataforma de inclusão digital que conecte estudantes e mentores voluntários.",
        "Engenharia": "Protótipo de monitoramento de consumo energético para salas de aula.",
        "Empreendedorismo": "Serviço local de economia circular para reaproveitamento de materiais escolares.",
    }.get(area, f"Uma solução simples para um problema real da comunidade ligado a {area}.")
    return {"texto": f"Ideia de portfólio: {idea}\n\nPróximo passo: descreva problema, público e primeira evidência no painel.", "tipo": "ideia", "provider": "local"}
