"""Camada de risco: calcula regra transparente com margem de faltas e suporte a modelo ML."""
def attendance_risk(attendances):
    records = list(attendances.all())
    total = len(records)
    if not total:
        return {
            "score": 0,
            "level": "Estável",
            "absence_rate": 0.0,
            "presence_rate": 100.0,
            "total_aulas": 0,
            "presencas": 0,
            "faltas": 0,
            "faltas_restantes": 5,
            "mensagem": "Sem registros de frequência até o momento."
        }

    presences = sum(item.presente for item in records)
    absences = total - presences
    rate = round(absences / total * 100, 1)
    presence_rate = round(100 - rate, 1)
    
    # Limite legal: 25% de faltas
    max_faltas_permitidas = int(total * 0.25)
    faltas_restantes = max(0, max_faltas_permitidas - absences)

    if rate >= 25:
        level = "Crítico"
        mensagem = f"Atenção! Você atingiu {rate}% de faltas (limite de 25%). Procure a orientação escolar."
    elif rate >= 15:
        level = "Atenção"
        mensagem = f"Alerta prudencial: {rate}% de faltas. Fique atento às próximas chamadas."
    else:
        level = "Estável"
        mensagem = "Excelente! Sua frequência está dentro do nível seguro."

    return {
        "score": min(100, round(rate * 4)),
        "level": level,
        "absence_rate": rate,
        "presence_rate": presence_rate,
        "total_aulas": total,
        "presencas": presences,
        "faltas": absences,
        "faltas_restantes": faltas_restantes,
        "mensagem": mensagem
    }

