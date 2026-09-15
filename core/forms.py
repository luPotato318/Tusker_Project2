import re
from django import forms
from django.contrib.auth import authenticate
from django.core.validators import validate_email
from django.db.models import Q
from .models import (
    ChallengeSubmission,
    JobOpportunity,
    PracticalChallenge,
    SoftSkillAssessment,
    StudentProject,
    SafeReport,
    User,
    Workshop,
)

def normalize_identifier(value):
    value = value.strip().lower()
    return re.sub(r"[^0-9]", "", value) if "@" not in value else value


def authenticate_identifier(value, password):
    """Permite entrar pelo identificador principal ou pelo e-mail de contato."""
    identifier = normalize_identifier(value)
    account = User.objects.filter(Q(identifier=identifier) | Q(email__iexact=identifier)).first()
    if not account:
        return None
    return authenticate(identifier=account.identifier, password=password)

class RegistrationForm(forms.Form):
    nome = forms.CharField(max_length=150, widget=forms.TextInput(attrs={"placeholder": "Seu nome completo"}))
    identifier = forms.CharField(label="CPF ou e-mail", max_length=150, widget=forms.TextInput(attrs={"placeholder": "Seu CPF (apenas números) ou e-mail"}))
    perfil_acesso = forms.ChoiceField(choices=[(User.Role.STUDENT, "Aluno")], widget=forms.HiddenInput())
    area_interesse = forms.CharField(max_length=100, required=False, widget=forms.TextInput(attrs={"placeholder": "Ex: Tecnologia da Informação, Psicologia..."}))
    senha = forms.CharField(widget=forms.PasswordInput(attrs={"placeholder": "Sua senha de acesso"}), min_length=8)

    def clean_identifier(self):
        identifier = normalize_identifier(self.cleaned_data["identifier"])
        if "@" in identifier:
            validate_email(identifier)
        if "@" not in identifier and (not identifier.isdigit() or len(identifier) != 11):
            raise forms.ValidationError("Informe um e-mail válido ou CPF com 11 dígitos.")
        if User.objects.filter(Q(identifier__iexact=identifier) | Q(email__iexact=identifier)).exists():
            raise forms.ValidationError("Este CPF ou e-mail já possui cadastro no sistema.")
        return identifier

    def save(self):
        data = self.cleaned_data.copy()
        password = data.pop("senha")
        return User.objects.create_user(password=password, **data)

class StudentLoginForm(forms.Form):
    """Formulário de Login exclusivo para Alunos e Corporativo."""
    identifier = forms.CharField(label="CPF ou e-mail", widget=forms.TextInput(attrs={"placeholder": "Digite seu CPF ou e-mail registrado"}))
    senha = forms.CharField(label="Senha", widget=forms.PasswordInput(attrs={"placeholder": "Sua senha"}))

    def clean(self):
        values = super().clean()
        identifier = normalize_identifier(values.get("identifier", ""))
        user = authenticate_identifier(identifier, values.get("senha"))
        if not user:
            raise forms.ValidationError("Acesso não encontrado. Confira se o CPF/e-mail e a senha estão corretos.")
        
        values["user"] = user
        return values

class AdminLoginForm(forms.Form):
    """Formulário de Login exclusivo para Administradores de Gestão."""
    identifier = forms.CharField(label="Identificador Administrativo (CPF/E-mail)", widget=forms.TextInput(attrs={"placeholder": "E-mail institucional ou CPF de Administrador"}))
    senha = forms.CharField(label="Senha de Acesso Restrito", widget=forms.PasswordInput(attrs={"placeholder": "Senha administrativa"}))

    def clean(self):
        values = super().clean()
        identifier = normalize_identifier(values.get("identifier", ""))
        user = authenticate_identifier(identifier, values.get("senha"))
        
        if not user:
            raise forms.ValidationError("Credenciais administrativas inválidas.")
        
        if user.perfil_acesso != User.Role.ADMIN and not user.is_staff:
            raise forms.ValidationError("Sua conta não possui permissões administrativas. Acesse o portal de alunos no menu principal.")
            
        values["user"] = user
        return values

class ProjectForm(forms.ModelForm):
    class Meta:
        model = StudentProject
        fields = ["titulo", "area", "resumo", "status", "link_projeto", "link_github", "publico"]
        widgets = {
            "titulo": forms.TextInput(attrs={"placeholder": "Nome do seu projeto ou protótipo"}),
            "resumo": forms.Textarea(attrs={"rows": 4, "placeholder": "Descreva o problema que seu projeto resolve..."}),
            "link_projeto": forms.URLInput(attrs={"placeholder": "https://..."}),
            "link_github": forms.URLInput(attrs={"placeholder": "https://github.com/..."}),
        }

class WorkshopForm(forms.ModelForm):
    class Meta:
        model = Workshop
        fields = [
            "titulo", "area", "status", "data", "inscricoes_ate", "duracao_minutos",
            "modalidade", "local", "descricao", "vagas", "escola", "mentor", "imagem_query",
        ]
        widgets = {
            "titulo": forms.TextInput(attrs={"placeholder": "Título da Oficina ou Workshop"}),
            "data": forms.DateTimeInput(format="%Y-%m-%dT%H:%M", attrs={"type": "datetime-local"}),
            "inscricoes_ate": forms.DateTimeInput(format="%Y-%m-%dT%H:%M", attrs={"type": "datetime-local"}),
            "descricao": forms.Textarea(attrs={"rows": 3, "placeholder": "Objetivos e conteúdo programático..."}),
            "vagas": forms.NumberInput(attrs={"min": 1, "max": 200}),
            "duracao_minutos": forms.NumberInput(attrs={"min": 30, "max": 600, "step": 15}),
            "local": forms.TextInput(attrs={"placeholder": "Sala, unidade ou link de acesso"}),
            "imagem_query": forms.TextInput(attrs={"placeholder": "Termos para a imagem do curso"}),
        }
        labels = {
            "titulo": "Título",
            "area": "Área",
            "data": "Data e horário",
            "inscricoes_ate": "Inscrições até",
            "duracao_minutos": "Duração em minutos",
            "local": "Local ou link",
            "descricao": "Descrição",
            "vagas": "Total de vagas",
            "escola": "Escola vinculada",
            "mentor": "Mentor responsável",
            "imagem_query": "Tema da imagem",
        }

    def __init__(self, *args, actor=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["data"].input_formats = ["%Y-%m-%dT%H:%M"]
        self.fields["inscricoes_ate"].input_formats = ["%Y-%m-%dT%H:%M"]
        self.fields["mentor"].queryset = User.objects.filter(
            Q(perfil_acesso=User.Role.TEACHER) | Q(perfil_acesso=User.Role.ADMIN),
            is_active=True,
        ).order_by("nome")
        if actor and not self.instance.pk:
            self.fields["mentor"].initial = actor.pk

    def clean(self):
        values = super().clean()
        event_date = values.get("data")
        enrollment_deadline = values.get("inscricoes_ate")
        if event_date and enrollment_deadline and enrollment_deadline > event_date:
            self.add_error("inscricoes_ate", "O encerramento das inscrições deve ocorrer antes do curso.")
        return values


class AdminUserForm(forms.ModelForm):
    senha_temporaria = forms.CharField(
        label="Senha temporária",
        required=False,
        min_length=8,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password", "placeholder": "Mínimo de 8 caracteres"}),
        help_text="Obrigatória no novo cadastro. Ao editar, deixe em branco para manter a senha atual.",
    )

    class Meta:
        model = User
        fields = [
            "identifier", "email", "nome", "perfil_acesso", "area_interesse", "escola", "turma",
            "competencias", "linkedin_url", "consentimento_vitrine", "is_active",
        ]
        widgets = {
            "identifier": forms.TextInput(attrs={"placeholder": "CPF ou e-mail de acesso"}),
            "email": forms.EmailInput(attrs={"placeholder": "contato@exemplo.com"}),
            "competencias": forms.Textarea(attrs={"rows": 3}),
        }
        labels = {
            "identifier": "CPF ou e-mail de acesso",
            "email": "E-mail de contato",
            "nome": "Nome completo",
            "perfil_acesso": "Papel no PIEM",
            "area_interesse": "Área de interesse",
            "escola": "Escola vinculada",
            "turma": "Turma vinculada",
            "competencias": "Competências",
            "linkedin_url": "Perfil no LinkedIn",
            "consentimento_vitrine": "Autoriza participação na vitrine",
            "is_active": "Conta ativa",
        }

    def clean_identifier(self):
        identifier = normalize_identifier(self.cleaned_data["identifier"])
        if "@" in identifier:
            validate_email(identifier)
        if "@" not in identifier and (not identifier.isdigit() or len(identifier) != 11):
            raise forms.ValidationError("Informe um e-mail válido ou CPF com 11 dígitos.")
        duplicate = User.objects.filter(Q(identifier__iexact=identifier) | Q(email__iexact=identifier)).exclude(pk=self.instance.pk)
        if duplicate.exists():
            raise forms.ValidationError("Este identificador já pertence a outra conta.")
        return identifier

    def clean(self):
        values = super().clean()
        identifier = values.get("identifier", "")
        email = (values.get("email") or "").strip().lower()
        if not email and "@" in identifier:
            email = identifier
            values["email"] = email
        if email and User.objects.filter(Q(email__iexact=email) | Q(identifier__iexact=email)).exclude(pk=self.instance.pk).exists():
            self.add_error("email", "Este e-mail já está associado a outra conta.")
        classroom = values.get("turma")
        school = values.get("escola")
        if classroom and school and classroom.escola_id != school.pk:
            self.add_error("turma", "A turma selecionada não pertence à escola informada.")
        if not self.instance.pk and not values.get("senha_temporaria"):
            self.add_error("senha_temporaria", "Defina uma senha temporária para o novo usuário.")
        return values

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = (user.email or "").strip().lower()
        password = self.cleaned_data.get("senha_temporaria")
        if password:
            user.set_password(password)
        user.is_staff = user.is_superuser or user.perfil_acesso == User.Role.ADMIN
        if commit:
            user.save()
            self.save_m2m()
        return user


class SafeReportStatusForm(forms.ModelForm):
    class Meta:
        model = SafeReport
        fields = ["status"]


class ChallengeForm(forms.ModelForm):
    class Meta:
        model = PracticalChallenge
        fields = ["titulo", "descricao", "area", "pontos", "prazo", "turma"]
        widgets = {
            "descricao": forms.Textarea(attrs={"rows": 4}),
            "prazo": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "pontos": forms.NumberInput(attrs={"min": 1, "max": 350}),
        }

    def __init__(self, *args, teacher=None, **kwargs):
        super().__init__(*args, **kwargs)
        if teacher and teacher.perfil_acesso == User.Role.TEACHER and not teacher.is_superuser:
            self.fields["turma"].queryset = teacher.turmas_docentes.all()
            self.fields["turma"].required = True


class ChallengeSubmissionForm(forms.ModelForm):
    class Meta:
        model = ChallengeSubmission
        fields = ["resposta", "anexo_url"]
        widgets = {
            "resposta": forms.Textarea(attrs={"rows": 6, "placeholder": "Descreva sua solução, processo e aprendizados."}),
            "anexo_url": forms.URLInput(attrs={"placeholder": "https://link-da-evidencia..."}),
        }


class SubmissionReviewForm(forms.ModelForm):
    class Meta:
        model = ChallengeSubmission
        fields = ["status", "pontos_atribuidos", "feedback"]
        widgets = {
            "pontos_atribuidos": forms.NumberInput(attrs={"min": 0}),
            "feedback": forms.Textarea(attrs={"rows": 4}),
        }

    def clean_pontos_atribuidos(self):
        points = self.cleaned_data["pontos_atribuidos"]
        if self.instance.desafio_id and points > self.instance.desafio.pontos:
            raise forms.ValidationError(f"O limite deste desafio é {self.instance.desafio.pontos} pontos.")
        return points


class SoftSkillAssessmentForm(forms.ModelForm):
    class Meta:
        model = SoftSkillAssessment
        fields = ["comunicacao", "proatividade", "trabalho_equipe", "feedback"]
        widgets = {
            "comunicacao": forms.NumberInput(attrs={"min": 1, "max": 5}),
            "proatividade": forms.NumberInput(attrs={"min": 1, "max": 5}),
            "trabalho_equipe": forms.NumberInput(attrs={"min": 1, "max": 5}),
            "feedback": forms.Textarea(attrs={"rows": 4}),
        }


class JobOpportunityForm(forms.ModelForm):
    class Meta:
        model = JobOpportunity
        fields = ["titulo", "empresa", "descricao", "competencias", "modalidade", "tipo", "localidade", "escola", "encerra_em"]
        widgets = {
            "descricao": forms.Textarea(attrs={"rows": 5}),
            "encerra_em": forms.DateTimeInput(attrs={"type": "datetime-local"}),
        }

    def __init__(self, *args, actor=None, **kwargs):
        super().__init__(*args, **kwargs)
        if actor and actor.perfil_acesso == User.Role.RECRUITER:
            self.fields["escola"].queryset = self.fields["escola"].queryset.filter(pk=actor.escola_id)
            self.fields["escola"].initial = actor.escola_id
            self.fields["escola"].widget = forms.HiddenInput()
