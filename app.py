# -*- coding: utf-8 -*-
"""
LOJA Performance Enterprise  -  v2.1
Sistema de gestão para oficina mecânica (Streamlit + SQLAlchemy + SQLite)

Novidades v2.1:
  * Aba de Finanças dedicada (Caixa, Formas de Pagamento e Recebimentos)
  * Ferramenta de Importação de cadastros do SHoficina (via planilhas CSV)
  * Suporte ampliado a cartões, Pix, dinheiro e prazos nas O.S.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import html
import io
import os
import re
import secrets
import sqlite3
import tempfile
import time
import urllib.parse
from contextlib import contextmanager
from xml.sax.saxutils import escape as xml_escape

import pandas as pd
import streamlit as st
from sqlalchemy import (Column, DateTime, Float, ForeignKey, Integer, String, Text,
                        create_engine, event, func, inspect, text)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import declarative_base, joinedload, relationship, sessionmaker

# --- Bibliotecas opcionais -----------------------------------------------------
try:
    import plotly.express as px
    PLOTLY_DISPONIVEL = True
except ImportError:  # pragma: no cover
    PLOTLY_DISPONIVEL = False

try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    REPORTLAB_DISPONIVEL = True
except ImportError:  # pragma: no cover
    REPORTLAB_DISPONIVEL = False

# ==============================================================================
# 1. CONFIGURAÇÃO DA PÁGINA E ESTILO
# ==============================================================================
st.set_page_config(
    page_title="LOJA Performance",
    page_icon="🏎️",
    layout="wide",
    initial_sidebar_state="expanded",
)

APP_VERSAO = "2.1"
DB_PATH = os.environ.get("OFICINA_DB", "oficina_enterprise.db")

_VER = tuple(int(p) for p in re.findall(r"\d+", st.__version__)[:2])
_LARGURA = {"width": "stretch"} if _VER >= (1, 50) else {"use_container_width": True}


def btn(label, **kw):
    return st.button(label, **_LARGURA, **kw)


def btn_form(label, **kw):
    return st.form_submit_button(label, **_LARGURA, **kw)


def btn_download(label, data, **kw):
    return st.download_button(label, data, **_LARGURA, **kw)


def tabela(df, **kw):
    return st.dataframe(df, hide_index=True, **_LARGURA, **kw)


def grafico(fig):
    st.plotly_chart(fig, **_LARGURA)


st.markdown(
    """
    <style>
    .block-container { padding-top: 1.6rem; max-width: 1500px; }
    #MainMenu, footer { visibility: hidden; }
    [data-testid="stSidebar"] { border-right: 1px solid #232A38; }
    .page-title { font-size: 1.75rem; font-weight: 800; color: #F0F4F8; margin: 0; letter-spacing: -.3px; }
    .page-title span { color: #FF3B30; }
    .page-sub { color: #8B97A8; margin: 2px 0 18px 0; font-size: .95rem; }
    .brand { font-weight: 900; font-size: 1.25rem; color: #FF3B30; letter-spacing: -.3px; }
    .brand small { display:block; color:#8B97A8; font-weight:600; font-size:.72rem; letter-spacing:1px; }
    div[data-testid="stMetric"] {
        background: #151922; border: 1px solid #232A38; border-radius: 10px; padding: 14px 16px;
    }
    div[data-testid="stMetricLabel"] p { color: #8B97A8 !important; font-size: .8rem; }
    div[data-testid="stForm"] { border: 1px solid #232A38; border-radius: 12px; padding: 20px; }
    .kcol-title { font-weight: 800; font-size: .85rem; letter-spacing: .6px; color: #CBD5E1;
                  border-bottom: 2px solid #232A38; padding-bottom: 6px; margin-bottom: 10px; }
    .kcard { background:#151922; border:1px solid #232A38; border-left:3px solid #FF3B30;
             border-radius:8px; padding:10px 12px; margin-bottom:8px; font-size:.85rem; line-height:1.35; }
    .kcard .k-top { display:flex; justify-content:space-between; font-weight:700; }
    .kcard .k-mut { color:#8B97A8; font-size:.78rem; }
    .kc-Aberta { border-left-color:#0A84FF; }
    .kc-EmAndamento { border-left-color:#FF9500; }
    .kc-AguardandoPeças { border-left-color:#FFD60A; }
    .badge { display:inline-block; padding:2px 10px; border-radius:999px; font-size:.75rem; font-weight:700;
             background:#232A38; color:#CBD5E1; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ==============================================================================
# 2. BANCO DE DADOS E MODELOS
# ==============================================================================
Base = declarative_base()
engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@event.listens_for(Engine, "connect")
def _ativar_foreign_keys(dbapi_conn, _record):
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


@contextmanager
def db():
    s = SessionLocal()
    try:
        yield s
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


class UsuarioModel(Base):
    __tablename__ = "usuarios"
    id = Column(Integer, primary_key=True, index=True)
    usuario = Column(String(50), unique=True, nullable=False)
    senha_hash = Column(String(255), nullable=False)
    perfil = Column(String(20), nullable=False)
    ativo = Column(Integer, default=1)
    trocar_senha = Column(Integer, default=0)
    ultimo_login = Column(DateTime)


class ClienteModel(Base):
    __tablename__ = "clientes"
    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String(100), nullable=False)
    telefone = Column(String(30))
    documento = Column(String(30))
    endereco = Column(String(200))
    email = Column(String(120))
    criado_em = Column(DateTime, default=dt.datetime.now)
    veiculos = relationship("VeiculoModel", back_populates="dono", cascade="all, delete-orphan")


class VeiculoModel(Base):
    __tablename__ = "veiculos"
    id = Column(Integer, primary_key=True, index=True)
    cliente_id = Column(Integer, ForeignKey("clientes.id"), nullable=False)
    placa = Column(String(10), unique=True, nullable=False, index=True)
    modelo = Column(String(100), nullable=False)
    ano = Column(String(10))
    cor = Column(String(30))
    km = Column(Integer, default=0)
    dono = relationship("ClienteModel", back_populates="veiculos")
    ordens_servico = relationship("OrdemServicoModel", back_populates="veiculo", cascade="all, delete-orphan")


class PecaModel(Base):
    __tablename__ = "pecas"
    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String(100), nullable=False)
    codigo = Column(String(50), unique=True, index=True)
    quantidade = Column(Integer, default=0)
    estoque_minimo = Column(Integer, default=3)
    preco_custo = Column(Float, default=0.0)
    preco_venda = Column(Float, default=0.0)


class OrdemServicoModel(Base):
    __tablename__ = "ordens_servico"
    id = Column(Integer, primary_key=True, index=True)
    veiculo_id = Column(Integer, ForeignKey("veiculos.id"), nullable=False)
    mecanico = Column(String(50), default="Não Atribuído")
    defeito = Column(Text, nullable=False)
    laudo = Column(Text, nullable=True)
    status = Column(String(30), default="Aberta")
    mao_de_obra = Column(Float, default=0.0)
    pecas_valor = Column(Float, default=0.0)
    valor_total = Column(Float, default=0.0)
    kit_utilizado = Column(String(100), default="Nenhum")
    estoque_baixado = Column(Integer, default=0)
    data_abertura = Column(DateTime, default=dt.datetime.now)
    desconto = Column(Float, default=0.0)
    forma_pagamento = Column(String(30), default="A definir")
    data_conclusao = Column(DateTime)
    km_entrada = Column(Integer, default=0)
    veiculo = relationship("VeiculoModel", back_populates="ordens_servico")
    itens = relationship("OrdemServicoItemModel", back_populates="os",
                         cascade="all, delete-orphan", order_by="OrdemServicoItemModel.id")


class OrdemServicoItemModel(Base):
    __tablename__ = "ordens_servico_itens"
    id = Column(Integer, primary_key=True)
    os_id = Column(Integer, ForeignKey("ordens_servico.id"), nullable=False, index=True)
    peca_id = Column(Integer, ForeignKey("pecas.id"), nullable=True)
    descricao = Column(String(150), nullable=False)
    quantidade = Column(Integer, default=1)
    preco_unit = Column(Float, default=0.0)
    baixado = Column(Integer, default=0)
    os = relationship("OrdemServicoModel", back_populates="itens")
    peca = relationship("PecaModel")


class MovimentoEstoqueModel(Base):
    __tablename__ = "movimentos_estoque"
    id = Column(Integer, primary_key=True)
    peca_id = Column(Integer, ForeignKey("pecas.id"), nullable=False, index=True)
    tipo = Column(String(20), nullable=False)
    quantidade = Column(Integer, nullable=False)
    motivo = Column(String(200))
    usuario = Column(String(50))
    timestamp = Column(DateTime, default=dt.datetime.now)
    peca = relationship("PecaModel")


class AgendamentoModel(Base):
    __tablename__ = "agendamentos"
    id = Column(Integer, primary_key=True, index=True)
    placa = Column(String(10), nullable=False)
    cliente_nome = Column(String(100), nullable=False)
    box = Column(String(20), nullable=False)
    data_hora = Column(DateTime, nullable=False)
    mecanico = Column(String(50))
    status = Column(String(20), default="Agendado")
    duracao_min = Column(Integer, default=60)
    observacao = Column(Text)


class AuditLogModel(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True, index=True)
    usuario = Column(String(50), nullable=False)
    acao = Column(String(100), nullable=False)
    detalhes = Column(Text)
    timestamp = Column(DateTime, default=dt.datetime.now)


class ConfiguracaoModel(Base):
    __tablename__ = "configuracoes"
    chave = Column(String(50), primary_key=True)
    valor = Column(Text)


_COLUNAS_NOVAS = {
    "usuarios": {"ativo": "INTEGER DEFAULT 1", "trocar_senha": "INTEGER DEFAULT 0", "ultimo_login": "DATETIME"},
    "clientes": {"email": "VARCHAR(120)", "criado_em": "DATETIME"},
    "veiculos": {"cor": "VARCHAR(30)", "km": "INTEGER DEFAULT 0"},
    "ordens_servico": {"desconto": "FLOAT DEFAULT 0", "forma_pagamento": "VARCHAR(30) DEFAULT 'A definir'",
                       "data_conclusao": "DATETIME", "km_entrada": "INTEGER DEFAULT 0"},
    "agendamentos": {"duracao_min": "INTEGER DEFAULT 60", "observacao": "TEXT"},
}

CONFIG_PADRAO = {
    "oficina_nome": "LOJA Performance",
    "oficina_cnpj": "",
    "oficina_telefone": "",
    "oficina_endereco": "",
    "comissao_pct": "20",
}

# ==============================================================================
# 3. CONSTANTES, SEGURANÇA E UTILITÁRIOS
# ==============================================================================
STATUS_OS = ["Aberta", "Em Andamento", "Aguardando Peças", "Concluída", "Cancelada"]
STATUS_ABERTOS = ["Aberta", "Em Andamento", "Aguardando Peças"]
STATUS_ICON = {"Aberta": "🔵", "Em Andamento": "🟠", "Aguardando Peças": "🟡", "Concluída": "🟢", "Cancelada": "⚫"}
STATUS_AG = ["Agendado", "Em Andamento", "Concluído", "Cancelado"]
BOXES = ["Box 01 - Rápido", "Box 02 - Elevador 1", "Box 03 - Elevador 2", "Box 04 - Diagnóstico"]

# Opções de Pagamento Expandidas conforme solicitado
FORMAS_PGTO = [
    "A definir",
    "Pix",
    "Dinheiro",
    "Cartão de Débito",
    "Cartão de Crédito (À vista)",
    "Cartão de Crédito (Parcelado)",
    "Boleto Bancário",
    "Crediário / A Prazo"
]

PERFIS = ["Administrador", "Atendimento", "Mecânico"]
SEM_MECANICO = "Não Atribuído"
CORES = ["#FF3B30", "#FF9500", "#34C759", "#0A84FF", "#8E8E93"]

PBKDF2_ITER = 200_000
PLACA_RE = re.compile(r"^[A-Z]{3}[0-9][A-Z0-9][0-9]{2}$")
USUARIO_RE = re.compile(r"^[a-z0-9_.-]{3,30}$")

PERMISSOES = {
    "excluir": {"Administrador"},
    "clientes": {"Administrador", "Atendimento"},
    "estoque_editar": {"Administrador", "Atendimento"},
    "financas": {"Administrador", "Atendimento"},
}


def pode(acao: str) -> bool:
    return st.session_state.get("perfil") in PERMISSOES.get(acao, set())


def hash_senha(senha: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", senha.encode(), bytes.fromhex(salt), PBKDF2_ITER).hex()
    return f"pbkdf2${PBKDF2_ITER}${salt}${dk}"


def verificar_senha(senha: str, armazenado: str) -> bool:
    if armazenado.startswith("pbkdf2$"):
        try:
            _, it, salt, dk = armazenado.split("$")
            calc = hashlib.pbkdf2_hmac("sha256", senha.encode(), bytes.fromhex(salt), int(it)).hex()
            return hmac.compare_digest(calc, dk)
        except ValueError:
            return False
    legado = hashlib.sha256(senha.encode()).hexdigest()
    return hmac.compare_digest(legado, armazenado)


def validar_senha_nova(senha: str) -> str | None:
    if len(senha) < 8:
        return "A senha deve ter pelo menos 8 caracteres."
    if not (re.search(r"[A-Za-z]", senha) and re.search(r"\d", senha)):
        return "A senha deve conter letras e números."
    return None


def brl(v) -> str:
    v = float(v or 0)
    return "R$ " + f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def normalizar_placa(p: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", p or "").upper()


def so_digitos(t: str) -> str:
    return "".join(ch for ch in str(t or "") if ch.isdigit())


def fmt_dt(d) -> str:
    return d.strftime("%d/%m/%Y %H:%M") if d else "—"


def humanizar(td: dt.timedelta) -> str:
    seg = int(td.total_seconds())
    if seg < 3600:
        return f"{max(seg // 60, 0)}min"
    if seg < 86400:
        return f"{seg // 3600}h"
    return f"{seg // 86400}d {(seg % 86400) // 3600}h"


def esc(t) -> str:
    return html.escape(str(t or ""))


def flash(msg: str, tipo: str = "success"):
    st.session_state.setdefault("_flash", []).append((tipo, msg))


def mostrar_flash():
    funcs = {"success": st.success, "error": st.error, "warning": st.warning, "info": st.info}
    for tipo, msg in st.session_state.pop("_flash", []):
        funcs.get(tipo, st.info)(msg)


def cabecalho(titulo: str, subtitulo: str = ""):
    st.markdown(f"<p class='page-title'>{esc(titulo)}</p>", unsafe_allow_html=True)
    st.markdown(f"<p class='page-sub'>{esc(subtitulo)}</p>", unsafe_allow_html=True)
    mostrar_flash()


def auditar(acao: str, detalhes: str = "", usuario: str | None = None):
    usuario = usuario or st.session_state.get("usuario", "sistema")
    with db() as s:
        s.add(AuditLogModel(usuario=usuario, acao=acao, detalhes=detalhes))
        s.commit()


def cfg_get(s) -> dict:
    cfg = dict(CONFIG_PADRAO)
    for c in s.query(ConfiguracaoModel).all():
        cfg[c.chave] = c.valor or ""
    return cfg


def cfg_set(s, chave: str, valor: str):
    item = s.get(ConfiguracaoModel, chave)
    if item:
        item.valor = valor
    else:
        s.add(ConfiguracaoModel(chave=chave, valor=valor))


# ==============================================================================
# 4. REGRAS DE NEGÓCIO (O.S., ESTOQUE, PDF, WHATSAPP, IMPORTAÇÃO SHOFICINA)
# ==============================================================================
def recalcular_os(o: OrdemServicoModel):
    pecas = sum((i.quantidade or 0) * (i.preco_unit or 0.0) for i in o.itens)
    o.pecas_valor = round(pecas, 2)
    bruto = (o.mao_de_obra or 0.0) + pecas
    o.valor_total = round(max(bruto - (o.desconto or 0.0), 0.0), 2)
    o.estoque_baixado = 1 if any(i.baixado for i in o.itens) else 0


def _mov(s, peca_id: int, tipo: str, qtd: int, motivo: str, usuario: str):
    s.add(MovimentoEstoqueModel(peca_id=peca_id, tipo=tipo, quantidade=qtd, motivo=motivo, usuario=usuario))


def sincronizar_estoque(s, o: OrdemServicoModel, usuario: str):
    concluida = o.status == "Concluída"
    for item in o.itens:
        if not item.peca_id:
            continue
        peca = s.get(PecaModel, item.peca_id)
        if peca is None:
            continue
        if concluida and not item.baixado:
            if (peca.quantidade or 0) < item.quantidade:
                raise ValueError(
                    f"Estoque insuficiente de '{peca.nome}': disponível {peca.quantidade}, necessário {item.quantidade}."
                )
            peca.quantidade -= item.quantidade
            item.baixado = 1
            _mov(s, peca.id, "SAÍDA", item.quantidade, f"O.S. #{o.id}", usuario)
        elif not concluida and item.baixado:
            peca.quantidade += item.quantidade
            item.baixado = 0
            _mov(s, peca.id, "ESTORNO", item.quantidade, f"O.S. #{o.id} reaberta/cancelada", usuario)


def estornar_item(s, o: OrdemServicoModel, item: OrdemServicoItemModel, usuario: str):
    if item.baixado and item.peca_id:
        peca = s.get(PecaModel, item.peca_id)
        if peca:
            peca.quantidade += item.quantidade
            _mov(s, peca.id, "ESTORNO", item.quantidade, f"Item removido da O.S. #{o.id}", usuario)


def aplicar_status(o: OrdemServicoModel, novo: str):
    o.status = novo
    if novo == "Concluída":
        o.data_conclusao = o.data_conclusao or dt.datetime.now()
    else:
        o.data_conclusao = None


def gerar_link_whatsapp(telefone, os_id, cliente, modelo, placa, status, valor, oficina) -> str:
    tel = so_digitos(telefone)
    if len(tel) <= 11 and not tel.startswith("55"):
        tel = "55" + tel
    msg = (
        f"Olá *{cliente}*! 🏎️\n\n"
        f"Atualização da sua Ordem de Serviço na *{oficina}*:\n\n"
        f"📌 *O.S. nº:* #{os_id}\n"
        f"🚘 *Veículo:* {modelo} (Placa: {placa})\n"
        f"🚦 *Status:* {status.upper()}\n"
        f"💰 *Valor Total:* {brl(valor)}\n\n"
        f"Qualquer dúvida, estamos à disposição!"
    )
    return f"https://wa.me/{tel}?text={urllib.parse.quote(msg)}"


def gerar_pdf_os(os_id: int):
    with db() as s:
        o = (s.query(OrdemServicoModel)
             .options(joinedload(OrdemServicoModel.veiculo).joinedload(VeiculoModel.dono),
                      joinedload(OrdemServicoModel.itens))
             .filter(OrdemServicoModel.id == os_id).first())
        if not o:
            return None
        cfg = cfg_get(s)
        v = o.veiculo
        cli = v.dono if v else None
        d = {
            "id": o.id, "abertura": o.data_abertura, "conclusao": o.data_conclusao, "status": o.status,
            "mecanico": o.mecanico, "defeito": o.defeito or "", "laudo": o.laudo or "",
            "mao": o.mao_de_obra or 0.0, "pecas": o.pecas_valor or 0.0, "desc": o.desconto or 0.0,
            "total": o.valor_total or 0.0, "pgto": o.forma_pagamento or "—", "km": o.km_entrada or 0,
            "cliente": cli.nome if cli else "N/A", "tel": (cli.telefone if cli else "") or "—",
            "doc": (cli.documento if cli else "") or "—",
            "veiculo": f"{v.modelo} ({v.ano or '—'})" if v else "N/A", "placa": v.placa if v else "N/A",
            "itens": [(i.descricao, i.quantidade or 0, i.preco_unit or 0.0) for i in o.itens],
        }

    if not REPORTLAB_DISPONIVEL:
        linhas = [f"{cfg['oficina_nome']} - O.S. #{d['id']}", f"Cliente: {d['cliente']}",
                  f"Veículo: {d['veiculo']} - {d['placa']}", f"Defeito: {d['defeito']}", ""]
        linhas += [f"{q}x {n}  {brl(p)}" for n, q, p in d["itens"]]
        linhas += ["", f"Mão de obra: {brl(d['mao'])}", f"Desconto: {brl(d['desc'])}", f"TOTAL: {brl(d['total'])}", f"Forma Pgto: {d['pgto']}"]
        return "\n".join(linhas).encode("utf-8"), "text/plain", "txt"

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=15 * mm, bottomMargin=15 * mm, title=f"O.S. {d['id']}")
    ss = getSampleStyleSheet()
    s_nome = ParagraphStyle("nome", parent=ss["Title"], fontSize=17, alignment=0, spaceAfter=2,
                            textColor=colors.HexColor("#C62828"))
    s_peq = ParagraphStyle("peq", parent=ss["Normal"], fontSize=8.5, textColor=colors.HexColor("#555555"), leading=11)
    s_dir = ParagraphStyle("dir", parent=ss["Normal"], fontSize=9, alignment=2, leading=12)
    s_h = ParagraphStyle("h", parent=ss["Heading3"], fontSize=10.5, spaceBefore=10, spaceAfter=4,
                         textColor=colors.HexColor("#222222"))
    s_txt = ParagraphStyle("t", parent=ss["BodyText"], fontSize=9.5, leading=13)
    s_cel = ParagraphStyle("c", parent=ss["Normal"], fontSize=9, leading=11)

    def par(txt, style=s_txt):
        return Paragraph(xml_escape(str(txt)).replace("\n", "<br/>"), style)

    info = " · ".join(x for x in [cfg["oficina_cnpj"], cfg["oficina_telefone"], cfg["oficina_endereco"]] if x)
    cab = Table([[
        [Paragraph(xml_escape(cfg["oficina_nome"]), s_nome), Paragraph(xml_escape(info) or "&nbsp;", s_peq)],
        Paragraph(f"<b>ORDEM DE SERVIÇO Nº {d['id']}</b><br/>Abertura: {fmt_dt(d['abertura'])}<br/>"
                  f"Status: <b>{xml_escape(d['status'].upper())}</b>", s_dir),
    ]], colWidths=[110 * mm, 64 * mm])
    cab.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                             ("LINEBELOW", (0, 0), (-1, 0), 1.2, colors.HexColor("#C62828")),
                             ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
    story = [cab, Spacer(1, 8)]

    dados = [
        ["Cliente", par(d["cliente"], s_cel), "Telefone", par(d["tel"], s_cel)],
        ["Documento", par(d["doc"], s_cel), "Mecânico", par(d["mecanico"], s_cel)],
        ["Veículo", par(d["veiculo"], s_cel), "Placa / Km", par(f"{d['placa']} / {d['km']} km", s_cel)],
    ]
    t = Table(dados, colWidths=[24 * mm, 63 * mm, 24 * mm, 63 * mm])
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"), ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9), ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F2F2F7")),
        ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#F2F2F7")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CCCCCC")), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story += [t, Paragraph("Defeito relatado", s_h), par(d["defeito"])]
    if d["laudo"]:
        story += [Paragraph("Laudo técnico / serviços executados", s_h), par(d["laudo"])]

    story.append(Paragraph("Peças e serviços", s_h))
    linhas = [["Descrição", "Qtd", "Unitário", "Total"]]
    for nome, q, p in d["itens"]:
        linhas.append([par(nome, s_cel), str(q), brl(p), brl(q * p)])
    if not d["itens"]:
        linhas.append([par("Nenhuma peça lançada", s_cel), "", "", ""])
    n_itens = len(linhas)
    linhas += [["", "", "Peças", brl(d["pecas"])], ["", "", "Mão de obra", brl(d["mao"])]]
    if d["desc"]:
        linhas.append(["", "", "Desconto", "- " + brl(d["desc"])])
    linhas.append(["", "", "TOTAL", brl(d["total"])])
    ti = Table(linhas, colWidths=[102 * mm, 14 * mm, 30 * mm, 28 * mm], repeatRows=1)
    ti.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1A1A21")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"), ("GRID", (0, 0), (-1, n_itens - 1), 0.4, colors.HexColor("#CCCCCC")),
        ("FONTNAME", (2, n_itens), (-1, -1), "Helvetica-Bold"), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEABOVE", (2, n_itens), (-1, n_itens), 0.8, colors.grey),
        ("BACKGROUND", (2, -1), (-1, -1), colors.HexColor("#FDECEA")), ("TEXTCOLOR", (2, -1), (-1, -1), colors.HexColor("#C62828")),
    ]))
    story += [ti, Spacer(1, 6), par(f"Forma de pagamento: <b>{d['pgto']}</b>", s_peq)]

    ass = Table([["_______________________________", "_______________________________"],
                 ["Responsável técnico", "Cliente (ciente e de acordo)"]], colWidths=[87 * mm, 87 * mm])
    ass.setStyle(TableStyle([("ALIGN", (0, 0), (-1, -1), "CENTER"), ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                             ("TOPPADDING", (0, 0), (-1, 0), 30)]))
    story += [Spacer(1, 14), ass, Spacer(1, 10),
              par(f"Documento gerado em {fmt_dt(dt.datetime.now())} · {cfg['oficina_nome']}", s_peq)]
    doc.build(story)
    return buf.getvalue(), "application/pdf", "pdf"


def backup_bytes() -> bytes:
    fd, caminho = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    origem = sqlite3.connect(DB_PATH)
    destino = sqlite3.connect(caminho)
    try:
        origem.backup(destino)
    finally:
        destino.close()
        origem.close()
    try:
        with open(caminho, "rb") as f:
            return f.read()
    finally:
        os.remove(caminho)


def importar_dados_shoficina(df: pd.DataFrame, tipo: str) -> tuple[int, int]:
    """Importa clientes, veículos ou peças exportados do SHoficina via CSV/Excel."""
    inseridos, ignorados = 0, 0
    with db() as s:
        for _, row in df.iterrows():
            if tipo == "clientes":
                nome = str(row.get("Nome", row.get("nome", "")) ).strip()
                if not nome or nome.lower() == "nan":
                    ignorados += 1
                    continue
                tel = so_digitos(str(row.get("Telefone", row.get("telefone", ""))))
                doc = str(row.get("Documento", row.get("documento", ""))).strip()
                end = str(row.get("Endereço", row.get("endereco", ""))).strip()
                email = str(row.get("Email", row.get("email", ""))).strip()
                
                # Evita duplicatas exatas por nome ou documento
                existe = s.query(ClienteModel).filter((ClienteModel.nome == nome) | (ClienteModel.documento == doc if doc else False)).first()
                if not existe:
                    s.add(ClienteModel(nome=nome, telefone=tel or None, documento=doc if doc else None,
                                       endereco=end if end else None, email=email if email else None))
                    inseridos += 1
                else:
                    ignorados += 1

            elif tipo == "veiculos":
                placa = normalizar_placa(str(row.get("Placa", row.get("placa", ""))))
                modelo = str(row.get("Modelo", row.get("modelo", ""))).strip()
                nome_cli = str(row.get("Cliente", row.get("cliente", ""))).strip()
                if not placa or not PLACA_RE.match(placa):
                    ignorados += 1
                    continue
                
                existe = s.query(VeiculoModel).filter(VeiculoModel.placa == placa).first()
                if not existe:
                    # Tenta achar o cliente pelo nome, senão vincula ao primeiro cliente
                    cli = s.query(ClienteModel).filter(ClienteModel.nome.ilike(f"%{nome_cli}%")).first() if nome_cli else None
                    if not cli:
                        cli = s.query(ClienteModel).first()
                    if cli:
                        s.add(VeiculoModel(cliente_id=cli.id, placa=placa, modelo=modelo or "Veículo SHoficina",
                                           ano=str(row.get("Ano", row.get("ano", ""))).strip()))
                        inseridos += 1
                    else:
                        ignorados += 1
                else:
                    ignorados += 1

            elif tipo == "pecas":
                nome = str(row.get("Peça", row.get("nome", row.get("Descricao", "")))).strip()
                codigo = str(row.get("Código", row.get("codigo", ""))).strip()
                if not nome or nome.lower() == "nan":
                    ignorados += 1
                    continue
                try:
                    qtd = int(float(row.get("Qtd", row.get("quantidade", 0))))
                except ValueError:
                    qtd = 0
                try:
                    venda = float(row.get("Venda", row.get("preco_venda", 0)))
                except ValueError:
                    venda = 0.0

                codigo = codigo or f"SH-{secrets.token_hex(3).upper()}"
                existe = s.query(PecaModel).filter(PecaModel.codigo == codigo).first()
                if not existe:
                    s.add(PecaModel(nome=nome, codigo=codigo, quantidade=qtd, preco_venda=venda))
                    inseridos += 1
                else:
                    ignorados += 1
        s.commit()
    return inseridos, ignorados


@st.cache_resource
def iniciar_banco():
    Base.metadata.create_all(bind=engine)
    insp = inspect(engine)
    with engine.begin() as conn:
        for tabela, cols in _COLUNAS_NOVAS.items():
            existentes = {c["name"] for c in insp.get_columns(tabela)}
            for nome, ddl in cols.items():
                if nome not in existentes:
                    conn.execute(text(f"ALTER TABLE {tabela} ADD COLUMN {nome} {ddl}"))
    with db() as s:
        if s.query(UsuarioModel).count() == 0:
            s.add(UsuarioModel(usuario="admin", senha_hash=hash_senha("admin123"),
                               perfil="Administrador", ativo=1, trocar_senha=1))
        else:
            legado = hashlib.sha256(b"admin123").hexdigest()
            for u in s.query(UsuarioModel).filter(UsuarioModel.senha_hash == legado):
                u.trocar_senha = 1
        for o in s.query(OrdemServicoModel).filter(OrdemServicoModel.kit_utilizado.isnot(None),
                                                   OrdemServicoModel.kit_utilizado != "Nenhum"):
            if not o.itens and (o.pecas_valor or 0) > 0:
                o.itens.append(OrdemServicoItemModel(descricao=o.kit_utilizado, quantidade=1,
                                                     preco_unit=o.pecas_valor, baixado=o.estoque_baixado or 0))
        s.commit()
    return True


# ==============================================================================
# 5. AUTENTICAÇÃO
# ==============================================================================
def alterar_senha(uid: int, nova: str, atual: str | None = None):
    erro = validar_senha_nova(nova)
    if erro:
        return False, erro
    with db() as s:
        u = s.get(UsuarioModel, uid)
        if not u:
            return False, "Usuário não encontrado."
        if atual is not None and not verificar_senha(atual, u.senha_hash):
            return False, "Senha atual incorreta."
        u.senha_hash = hash_senha(nova)
        u.trocar_senha = 0
        s.commit()
    return True, "Senha alterada com sucesso."


def tela_login():
    _, c, _ = st.columns([1, 1.3, 1])
    with c:
        st.markdown("<div style='text-align:center;margin-top:8vh'><p class='page-title' style='font-size:2.3rem'>"
                    "🏎️ LOJA <span>PERFORMANCE</span></p><p class='page-sub'>Sistema de gestão da oficina</p></div>",
                    unsafe_allow_html=True)
        with st.form("form_login"):
            usuario = st.text_input("Usuário").strip().lower()
            senha = st.text_input("Senha", type="password")
            entrar = btn_form("Entrar", type="primary")
        if not entrar:
            return
        agora = time.time()
        bloqueio = st.session_state.get("bloqueado_ate", 0)
        if agora < bloqueio:
            st.error(f"Muitas tentativas incorretas. Aguarde {int(bloqueio - agora)}s.")
            return
        dados = None
        with db() as s:
            u = s.query(UsuarioModel).filter(UsuarioModel.usuario == usuario).first()
            if u and (u.ativo is None or u.ativo == 1) and verificar_senha(senha, u.senha_hash):
                if not u.senha_hash.startswith("pbkdf2$"):
                    u.senha_hash = hash_senha(senha)
                u.ultimo_login = dt.datetime.now()
                s.commit()
                dados = (u.id, u.usuario, u.perfil, bool(u.trocar_senha))
        if dados:
            st.session_state.update(autenticado=True, uid=dados[0], usuario=dados[1], perfil=dados[2],
                                    trocar_senha=dados[3], tentativas=0)
            auditar("LOGIN", f"Perfil: {dados[2]}", usuario=dados[1])
            st.rerun()
        else:
            st.session_state["tentativas"] = st.session_state.get("tentativas", 0) + 1
            if st.session_state["tentativas"] >= 5:
                st.session_state["bloqueado_ate"] = agora + 60
                st.session_state["tentativas"] = 0
            auditar("LOGIN_FALHA", f"Usuário informado: {usuario}", usuario="sistema")
            st.error("Usuário ou senha inválidos.")


def tela_troca_obrigatoria():
    _, c, _ = st.columns([1, 1.3, 1])
    with c:
        st.markdown("<p class='page-title' style='margin-top:8vh'>🔐 Defina uma nova senha</p>"
                    "<p class='page-sub'>Por segurança, é necessário trocar a senha antes de continuar.</p>",
                    unsafe_allow_html=True)
        with st.form("form_troca"):
            nova = st.text_input("Nova senha", type="password", help="Mínimo de 8 caracteres, com letras e números.")
            conf = st.text_input("Confirmar nova senha", type="password")
            ok = btn_form("Salvar nova senha", type="primary")
        if ok:
            if nova != conf:
                st.error("As senhas não conferem.")
            else:
                sucesso, msg = alterar_senha(st.session_state["uid"], nova)
                if sucesso:
                    auditar("TROCA_SENHA", "Troca obrigatória")
                    st.session_state["trocar_senha"] = False
                    st.rerun()
                else:
                    st.error(msg)
        if btn("Sair"):
            st.session_state.clear()
            st.rerun()


# ==============================================================================
# 6. HELPERS DE CONSULTA
# ==============================================================================
def lista_mecanicos(s) -> list[str]:
    nomes = {u.usuario for u in s.query(UsuarioModel).filter(UsuarioModel.perfil == "Mecânico")
             if u.ativo is None or u.ativo == 1}
    nomes |= {m for (m,) in s.query(OrdemServicoModel.mecanico).distinct() if m}
    nomes.discard(SEM_MECANICO)
    return [SEM_MECANICO] + sorted(nomes)


def mapa_veiculos(s) -> dict:
    rows = s.query(VeiculoModel).options(joinedload(VeiculoModel.dono)).order_by(VeiculoModel.placa).all()
    return {v.id: f"{v.placa} · {v.modelo} · {v.dono.nome if v.dono else 'Sem proprietário'}" for v in rows}


def os_query(s):
    return (s.query(OrdemServicoModel)
            .options(joinedload(OrdemServicoModel.veiculo).joinedload(VeiculoModel.dono))
            .outerjoin(VeiculoModel, OrdemServicoModel.veiculo_id == VeiculoModel.id)
            .outerjoin(ClienteModel, VeiculoModel.cliente_id == ClienteModel.id))


def confirmar_exclusao(label: str, chave: str, aviso: str = "Esta ação não pode ser desfeita.") -> bool:
    with st.popover(label):
        st.warning(aviso)
        return st.button("Confirmar exclusão", key=chave, type="primary")


def estilizar(fig, altura: int = 340):
    fig.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      margin=dict(l=10, r=10, t=50, b=10), height=altura, font=dict(color="#CBD5E1"),
                      legend_title_text="")
    fig.update_xaxes(gridcolor="#1E2433")
    fig.update_yaxes(gridcolor="#1E2433")
    return fig


def filtro_periodo(chave: str):
    hoje = dt.date.today()
    p = st.date_input("Período", value=(hoje.replace(day=1), hoje), key=chave, format="DD/MM/YYYY")
    if isinstance(p, (list, tuple)):
        return (p[0], p[1] if len(p) > 1 else p[0])
    return p, p


# ==============================================================================
# 7. PÁGINAS
# ==============================================================================
# ------------------------------------------------------------------ PAINEL ----
def pagina_painel():
    cabecalho("Painel Operacional", f"Visão geral da oficina · {dt.date.today().strftime('%d/%m/%Y')}")
    hoje = dt.date.today()
    ini_dia = dt.datetime.combine(hoje, dt.time.min)
    fim_dia = ini_dia + dt.timedelta(days=1)
    admin = st.session_state["perfil"] in ("Administrador", "Atendimento")

    with db() as s:
        n_fila = s.query(func.count(OrdemServicoModel.id)).filter(OrdemServicoModel.status.in_(STATUS_ABERTOS)).scalar()
        n_aguard = s.query(func.count(OrdemServicoModel.id)).filter(OrdemServicoModel.status == "Aguardando Peças").scalar()
        n_ag = (s.query(func.count(AgendamentoModel.id))
                .filter(AgendamentoModel.data_hora >= ini_dia, AgendamentoModel.data_hora < fim_dia,
                        AgendamentoModel.status.in_(["Agendado", "Em Andamento"])).scalar())
        n_baixo = s.query(func.count(PecaModel.id)).filter(PecaModel.quantidade <= PecaModel.estoque_minimo).scalar()

        cols = st.columns(5 if admin else 4)
        cols[0].metric("O.S. na fila", n_fila)
        cols[1].metric("Aguardando peças", n_aguard)
        cols[2].metric("Agendamentos hoje", n_ag)
        cols[3].metric("Estoque em alerta", n_baixo)
        if admin:
            ini_mes = dt.datetime.combine(hoje.replace(day=1), dt.time.min)
            ref = func.coalesce(OrdemServicoModel.data_conclusao, OrdemServicoModel.data_abertura)
            fat = (s.query(func.coalesce(func.sum(OrdemServicoModel.valor_total), 0.0))
                   .filter(OrdemServicoModel.status == "Concluída", ref >= ini_mes).scalar())
            cols[4].metric("Faturamento do mês", brl(fat))

        st.markdown("#### Quadro de O.S.")
        kcols = st.columns(3)
        agora = dt.datetime.now()
        for col, status in zip(kcols, STATUS_ABERTOS):
            q = os_query(s).filter(OrdemServicoModel.status == status)
            total = q.count()
            ordens = q.order_by(OrdemServicoModel.data_abertura.asc()).limit(8).all()
            with col:
                st.markdown(f"<div class='kcol-title'>{STATUS_ICON[status]} {status.upper()} · {total}</div>",
                            unsafe_allow_html=True)
                if not ordens:
                    st.caption("Nenhuma O.S. nesta etapa.")
                for o in ordens:
                    v = o.veiculo
                    cli = v.dono.nome if v and v.dono else "Sem cliente"
                    st.markdown(
                        f"<div class='kcard kc-{status.replace(' ', '')}'>"
                        f"<div class='k-top'><span>#{o.id} · {esc(v.placa if v else 'N/A')}</span>"
                        f"<span class='k-mut'>{humanizar(agora - o.data_abertura)}</span></div>"
                        f"<div>{esc(v.modelo if v else '')}</div>"
                        f"<div class='k-mut'>{esc(cli)} · 🔧 {esc(o.mecanico)}</div></div>",
                        unsafe_allow_html=True)
                if total > 8:
                    st.caption(f"+ {total - 8} na tela de Ordens de Serviço")

        c1, c2 = st.columns(2)
        with c1:
            st.markdown("#### Agenda de hoje")
            ags = (s.query(AgendamentoModel)
                   .filter(AgendamentoModel.data_hora >= ini_dia, AgendamentoModel.data_hora < fim_dia)
                   .order_by(AgendamentoModel.data_hora).all())
            if ags:
                tabela(pd.DataFrame([{"Hora": a.data_hora.strftime("%H:%M"), "Placa": a.placa, "Cliente": a.cliente_nome,
                                      "Box": a.box, "Status": a.status} for a in ags]))
            else:
                st.caption("Sem agendamentos para hoje.")
        with c2:
            st.markdown("#### Alertas de estoque")
            baixos = (s.query(PecaModel).filter(PecaModel.quantidade <= PecaModel.estoque_minimo)
                      .order_by(PecaModel.quantidade).limit(10).all())
            if baixos:
                tabela(pd.DataFrame([{"Peça": p.nome, "Qtd": p.quantidade, "Mínimo": p.estoque_minimo} for p in baixos]))
            else:
                st.caption("Nenhuma peça abaixo do mínimo. ✅")


# ------------------------------------------------------------------ O.S. -------
def pagina_os():
    cabecalho("Ordens de Serviço", "Abertura, acompanhamento, peças e documentos")
    tab_nova, tab_ger = st.tabs(["➕ Nova O.S.", "📋 Gerenciar O.S."])

    with tab_nova:
        with db() as s:
            veics = mapa_veiculos(s)
            mecs = lista_mecanicos(s)
        if not veics:
            st.info("Cadastre um cliente e um veículo em **Clientes & Garagem** antes de abrir uma O.S.")
        else:
            with st.form("form_nova_os", clear_on_submit=True):
                vid = st.selectbox("Veículo", list(veics), format_func=lambda i: veics[i], index=None,
                                   placeholder="Digite a placa, modelo ou cliente...")
                c1, c2, c3 = st.columns(3)
                mec = c1.selectbox("Mecânico responsável", mecs)
                km = c2.number_input("Km na entrada", min_value=0, step=100)
                status = c3.selectbox("Status inicial", STATUS_ABERTOS)
                defeito = st.text_area("Defeito relatado / solicitação do cliente")
                c4, c5, c6 = st.columns(3)
                mao = c4.number_input("Mão de obra (R$)", min_value=0.0, step=10.0)
                desc = c5.number_input("Desconto (R$)", min_value=0.0, step=5.0)
                pgto = c6.selectbox("Forma de pagamento", FORMAS_PGTO)
                criar = btn_form("Abrir O.S.", type="primary")
            if criar:
                if vid is None or not defeito.strip():
                    st.error("Selecione o veículo e descreva o defeito.")
                elif desc > mao:
                    st.error("Sem peças lançadas, o desconto não pode exceder a mão de obra.")
                else:
                    with db() as s:
                        o = OrdemServicoModel(veiculo_id=vid, mecanico=mec, defeito=defeito.strip(), status=status,
                                              mao_de_obra=mao, desconto=desc, forma_pagamento=pgto, km_entrada=int(km))
                        s.add(o)
                        s.flush()
                        recalcular_os(o)
                        s.commit()
                        novo_id = o.id
                    auditar("CRIAR_OS", f"O.S. #{novo_id} criada")
                    st.session_state["os_sel"] = novo_id
                    flash(f"O.S. #{novo_id} aberta! Vá em **Gerenciar O.S.** para lançar peças e emitir o PDF.")
                    st.rerun()

    with tab_ger:
        f1, f2, f3 = st.columns([2, 2, 1])
        busca = f1.text_input("Buscar", placeholder="Placa, cliente, modelo ou nº da O.S.").strip()
        filtro = f2.multiselect("Status", STATUS_OS, default=[x for x in STATUS_OS if x != "Cancelada"])
        limite = f3.selectbox("Exibir", [25, 50, 100, 250], index=1)
        with db() as s:
            q = os_query(s)
            if filtro:
                q = q.filter(OrdemServicoModel.status.in_(filtro))
            if busca:
                t = f"%{busca}%"
                cond = (VeiculoModel.placa.ilike(t)) | (ClienteModel.nome.ilike(t)) | (VeiculoModel.modelo.ilike(t))
                if busca.isdigit():
                    cond = cond | (OrdemServicoModel.id == int(busca))
                q = q.filter(cond)
            total_enc = q.count()
            ordens = q.order_by(OrdemServicoModel.id.desc()).limit(limite).all()
            linhas, rotulos = [], {}
            for o in ordens:
                v = o.veiculo
                cli = v.dono.nome if v and v.dono else "—"
                linhas.append({"O.S.": o.id, "Status": f"{STATUS_ICON.get(o.status, '')} {o.status}",
                               "Placa": v.placa if v else "—", "Modelo": v.modelo if v else "—", "Cliente": cli,
                               "Mecânico": o.mecanico, "Pagamento": o.forma_pagamento, "Abertura": o.data_abertura, "Total": o.valor_total or 0.0})
                rotulos[o.id] = f"#{o.id} · {v.placa if v else '—'} · {v.modelo if v else ''} · {cli} · {o.status}"

        if not linhas:
            st.info("Nenhuma Ordem de Serviço encontrada com os filtros atuais.")
            return
        st.caption(f"{total_enc} O.S. encontrada(s)" + (f" · exibindo as {limite} mais recentes" if total_enc > limite else ""))
        tabela(pd.DataFrame(linhas), column_config={
            "Total": st.column_config.NumberColumn(format="R$ %.2f"),
            "Abertura": st.column_config.DatetimeColumn(format="DD/MM/YYYY HH:mm"),
        }, height=260)

        ids = list(rotulos)
        if st.session_state.get("os_sel") not in ids:
            st.session_state.pop("os_sel", None)
        sel = st.selectbox("Selecione a O.S. para detalhar", ids, format_func=lambda i: rotulos[i], key="os_sel")
        st.divider()
        detalhe_os(sel)


def detalhe_os(os_id: int):
    usuario = st.session_state["usuario"]
    with db() as s:
        o = (os_query(s).options(joinedload(OrdemServicoModel.itens).joinedload(OrdemServicoItemModel.peca))
             .filter(OrdemServicoModel.id == os_id).first())
        if not o:
            st.error("O.S. não encontrada.")
            return
        v = o.veiculo
        cli = v.dono if v else None
        cfg = cfg_get(s)

        m = st.columns(4)
        m[0].metric("Status", f"{STATUS_ICON.get(o.status, '')} {o.status}")
        m[1].metric("Veículo", f"{v.placa} · {v.modelo}" if v else "—")
        m[2].metric("Pagamento", o.forma_pagamento or "A definir")
        m[3].metric("Total", brl(o.valor_total))

        t_dados, t_itens, t_docs = st.tabs(["📝 Dados e status", "🔩 Peças e serviços", "📄 Documentos e ações"])

        with t_dados:
            mecs = lista_mecanicos(s)
            if o.mecanico not in mecs:
                mecs.append(o.mecanico)
            with st.form(f"form_os_{o.id}"):
                c1, c2 = st.columns(2)
                e_mec = c1.selectbox("Mecânico", mecs, index=mecs.index(o.mecanico), key=f"mec_{o.id}")
                e_km = c2.number_input("Km na entrada", min_value=0, value=int(o.km_entrada or 0), step=100, key=f"km_{o.id}")
                e_def = st.text_area("Defeito relatado", value=o.defeito, key=f"def_{o.id}")
                e_laudo = st.text_area("Laudo técnico / serviços executados", value=o.laudo or "", key=f"laudo_{o.id}")
                c3, c4, c5, c6 = st.columns(4)
                e_mao = c3.number_input("Mão de obra (R$)", min_value=0.0, value=float(o.mao_de_obra or 0), step=10.0, key=f"mao_{o.id}")
                e_desc = c4.number_input("Desconto (R$)", min_value=0.0, value=float(o.desconto or 0), step=5.0, key=f"desc_{o.id}")
                pg_atual = o.forma_pagamento if o.forma_pagamento in FORMAS_PGTO else FORMAS_PGTO[0]
                e_pg = c5.selectbox("Forma de pagamento", FORMAS_PGTO, index=FORMAS_PGTO.index(pg_atual), key=f"pg_{o.id}")
                st_atual = o.status if o.status in STATUS_OS else STATUS_OS[0]
                e_st = c6.selectbox("Status", STATUS_OS, index=STATUS_OS.index(st_atual), key=f"st_{o.id}")
                salvar = btn_form("💾 Salvar alterações", type="primary")
            if salvar:
                if not e_def.strip():
                    st.error("O defeito relatado não pode ficar vazio.")
                elif e_desc > e_mao + (o.pecas_valor or 0):
                    st.error("O desconto não pode ser maior que o valor total de peças + mão de obra.")
                else:
                    antigo = o.status
                    try:
                        o.mecanico, o.km_entrada, o.defeito, o.laudo = e_mec, int(e_km), e_def.strip(), e_laudo.strip()
                        o.mao_de_obra, o.desconto, o.forma_pagamento = e_mao, e_desc, e_pg
                        aplicar_status(o, e_st)
                        recalcular_os(o)
                        sincronizar_estoque(s, o, usuario)
                        recalcular_os(o)
                        s.commit()
                    except ValueError as e:
                        s.rollback()
                        st.error(str(e))
                    else:
                        st.session_state.pop(f"pdf_{o.id}", None)
                        auditar("EDITAR_OS", f"O.S. #{o.id}: {antigo} → {e_st} | Pgto: {e_pg}")
                        flash("O.S. atualizada com sucesso.")
                        st.rerun()

        with t_itens:
            if o.itens:
                h = st.columns([5, 1, 2, 2, 1])
                for col, txt in zip(h, ["Descrição", "Qtd", "Unitário", "Total", ""]):
                    col.caption(txt)
                for it in list(o.itens):
                    c = st.columns([5, 1, 2, 2, 1])
                    c[0].write(("📦 " if it.peca_id else "🔹 ") + it.descricao + (" · _baixado_" if it.baixado else ""))
                    c[1].write(it.quantidade)
                    c[2].write(brl(it.preco_unit))
                    c[3].write(brl((it.quantidade or 0) * (it.preco_unit or 0)))
                    if c[4].button("🗑️", key=f"rm_{it.id}", help="Remover item"):
                        estornar_item(s, o, it, usuario)
                        o.itens.remove(it)
                        s.flush()
                        recalcular_os(o)
                        s.commit()
                        st.session_state.pop(f"pdf_{o.id}", None)
                        auditar("REMOVER_ITEM", f"O.S. #{o.id}: {it.descricao}")
                        st.rerun()
                r = st.columns(4)
                r[0].metric("Peças", brl(o.pecas_valor))
                r[1].metric("Mão de obra", brl(o.mao_de_obra))
                r[2].metric("Desconto", brl(o.desconto))
                r[3].metric("Total", brl(o.valor_total))
            else:
                st.info("Nenhum item lançado nesta O.S.")

            st.markdown("##### Adicionar item")
            pecas = s.query(PecaModel).order_by(PecaModel.nome).all()
            rot_pecas = {0: "— Item avulso (digitar descrição) —"}
            rot_pecas.update({p.id: f"{p.codigo or 's/ref'} · {p.nome} · estoque {p.quantidade} · {brl(p.preco_venda)}" for p in pecas})
            with st.form(f"form_item_{o.id}", clear_on_submit=True):
                psel = st.selectbox("Peça do estoque", list(rot_pecas), format_func=lambda i: rot_pecas[i], key=f"psel_{o.id}")
                c1, c2, c3 = st.columns([3, 1, 1])
                livre = c1.text_input("Descrição (somente item avulso)", key=f"livre_{o.id}")
                qtd = c2.number_input("Qtd", min_value=1, step=1, key=f"qtd_{o.id}")
                preco = c3.number_input("Preço unit. (R$)", min_value=0.0, step=5.0, key=f"preco_{o.id}",
                                        help="Para peças do estoque, deixe 0,00 para usar o preço de venda cadastrado.")
                add = btn_form("Adicionar item")
            if add:
                if psel == 0 and not livre.strip():
                    st.error("Selecione uma peça do estoque ou descreva o item avulso.")
                else:
                    peca = s.get(PecaModel, psel) if psel else None
                    try:
                        o.itens.append(OrdemServicoItemModel(
                            peca_id=peca.id if peca else None,
                            descricao=peca.nome if peca else livre.strip(),
                            quantidade=int(qtd),
                            preco_unit=float(preco or (peca.preco_venda if peca else 0.0))))
                        recalcular_os(o)
                        sincronizar_estoque(s, o, usuario)
                        recalcular_os(o)
                        s.commit()
                    except ValueError as e:
                        s.rollback()
                        st.error(str(e))
                    else:
                        st.session_state.pop(f"pdf_{o.id}", None)
                        auditar("ADD_ITEM", f"O.S. #{o.id}: {qtd}x {peca.nome if peca else livre.strip()}")
                        flash("Item adicionado.")
                        st.rerun()

        with t_docs:
            c1, c2, c3 = st.columns(3)
            with c1:
                if btn("📄 Gerar PDF da O.S.", key=f"genpdf_{o.id}"):
                    st.session_state[f"pdf_{o.id}"] = gerar_pdf_os(o.id)
                pdf = st.session_state.get(f"pdf_{o.id}")
                if pdf:
                    btn_download("⬇️ Baixar arquivo", pdf[0], file_name=f"OS_{o.id}.{pdf[2]}", mime=pdf[1], key=f"dl_{o.id}")
            with c2:
                if cli and cli.telefone and so_digitos(cli.telefone):
                    link = gerar_link_whatsapp(cli.telefone, o.id, cli.nome, v.modelo, v.placa, o.status,
                                               o.valor_total, cfg["oficina_nome"])
                    st.link_button("💬 Notificar por WhatsApp", link)
                else:
                    st.caption("Cliente sem telefone cadastrado.")
            with c3:
                if pode("excluir"):
                    if confirmar_exclusao("🗑️ Excluir O.S.", f"del_os_{o.id}",
                                          "O estoque baixado por esta O.S. será estornado."):
                        for it in list(o.itens):
                            estornar_item(s, o, it, usuario)
                        s.delete(o)
                        s.commit()
                        auditar("EXCLUIR_OS", f"O.S. #{os_id} excluída")
                        st.session_state.pop("os_sel", None)
                        flash(f"O.S. #{os_id} excluída.", "warning")
                        st.rerun()
                else:
                    st.caption("Exclusão restrita ao administrador.")


# ------------------------------------------------------------------ AGENDA -----
def conflitos_box(s, box, inicio, duracao, ignorar_id=None):
    fim = inicio + dt.timedelta(minutes=duracao)
    cand = (s.query(AgendamentoModel)
            .filter(AgendamentoModel.box == box, AgendamentoModel.status.in_(["Agendado", "Em Andamento"]),
                    AgendamentoModel.data_hora > inicio - dt.timedelta(hours=12), AgendamentoModel.data_hora < fim).all())
    return [a for a in cand if a.id != ignorar_id and a.data_hora < fim
            and a.data_hora + dt.timedelta(minutes=a.duracao_min or 60) > inicio]


def pagina_agenda():
    cabecalho("Agenda e Controle de Box", "Horários de entrada, ocupação dos boxes e conversão em O.S.")
    tab_novo, tab_ag = st.tabs(["➕ Novo agendamento", "📅 Agenda"])

    with tab_novo:
        with db() as s:
            veics = mapa_veiculos(s)
            mecs = lista_mecanicos(s)
        opcoes = list(veics) + [0]
        rot = dict(veics)
        rot[0] = "➕ Veículo não cadastrado (digitar)"
        vsel = st.selectbox("Veículo", opcoes, format_func=lambda i: rot[i], index=None,
                            placeholder="Selecione o veículo...", key="ag_veic")
        placa_man = cli_man = ""
        if vsel == 0:
            c1, c2 = st.columns(2)
            placa_man = normalizar_placa(c1.text_input("Placa", key="ag_placa_man"))
            cli_man = c2.text_input("Nome do cliente", key="ag_cli_man").strip()
        c1, c2, c3 = st.columns(3)
        box = c1.selectbox("Box", BOXES, key="ag_box")
        mec = c2.selectbox("Mecânico escalado", mecs, key="ag_mec")
        dur = c3.selectbox("Duração prevista", [30, 60, 90, 120, 180, 240], index=1,
                           format_func=lambda m: f"{m} min", key="ag_dur")
        c4, c5 = st.columns(2)
        data = c4.date_input("Data", dt.date.today(), format="DD/MM/YYYY", key="ag_data")
        hora = c5.time_input("Horário", dt.time(9, 0), step=1800, key="ag_hora")
        obs = st.text_area("Observações", key="ag_obs")
        if btn("Agendar entrada", type="primary", key="ag_salvar"):
            inicio = dt.datetime.combine(data, hora)
            if vsel is None:
                st.error("Selecione o veículo.")
            elif vsel == 0 and (not PLACA_RE.match(placa_man) or not cli_man):
                st.error("Informe uma placa válida (ABC1D23) e o nome do cliente.")
            else:
                with db() as s:
                    if vsel and vsel != 0:
                        v = s.query(VeiculoModel).options(joinedload(VeiculoModel.dono)).get(vsel)
                        placa, cliente = v.placa, (v.dono.nome if v.dono else "—")
                    else:
                        placa, cliente = placa_man, cli_man
                    conf = conflitos_box(s, box, inicio, dur)
                    if conf:
                        a = conf[0]
                        st.error(f"Conflito: {box} já está ocupado por {a.placa} às {a.data_hora.strftime('%H:%M')}.")
                    else:
                        s.add(AgendamentoModel(placa=placa, cliente_nome=cliente, box=box, mecanico=mec,
                                               data_hora=inicio, duracao_min=dur, observacao=obs.strip()))
                        s.commit()
                        auditar("AGENDAR", f"{placa} em {box} - {fmt_dt(inicio)}")
                        for k in ("ag_veic", "ag_obs"):
                            st.session_state.pop(k, None)
                        flash("Agendamento confirmado!")
                        st.rerun()

    with tab_ag:
        hoje = dt.date.today()
        c1, c2 = st.columns([2, 2])
        per = c1.date_input("Período", value=(hoje, hoje + dt.timedelta(days=7)), format="DD/MM/YYYY", key="ag_per")
        filtro = c2.multiselect("Status", STATUS_AG, default=["Agendado", "Em Andamento"], key="ag_filtro")
        d1, d2 = (per[0], per[1] if len(per) > 1 else per[0]) if isinstance(per, (list, tuple)) else (per, per)
        ini = dt.datetime.combine(d1, dt.time.min)
        fim = dt.datetime.combine(d2, dt.time.max)
        with db() as s:
            q = s.query(AgendamentoModel).filter(AgendamentoModel.data_hora >= ini, AgendamentoModel.data_hora <= fim)
            if filtro:
                q = q.filter(AgendamentoModel.status.in_(filtro))
            ags = q.order_by(AgendamentoModel.data_hora).all()
            if not ags:
                st.info("Nenhum agendamento no período.")
                return
            tabela(pd.DataFrame([{"ID": a.id, "Data/Hora": a.data_hora, "Placa": a.placa, "Cliente": a.cliente_nome,
                                  "Box": a.box, "Mecânico": a.mecanico, "Duração (min)": a.duracao_min or 60,
                                  "Status": a.status} for a in ags]),
                   column_config={"Data/Hora": st.column_config.DatetimeColumn(format="DD/MM/YYYY HH:mm")}, height=260)

            rot = {a.id: f"#{a.id} · {fmt_dt(a.data_hora)} · {a.placa} · {a.cliente_nome} · {a.status}" for a in ags}
            sid = st.selectbox("Selecione para editar", list(rot), format_func=lambda i: rot[i], key="ag_sel")
            a = s.get(AgendamentoModel, sid)
            mecs = lista_mecanicos(s)
            if a.mecanico and a.mecanico not in mecs:
                mecs.append(a.mecanico)
            with st.form(f"form_ag_{a.id}"):
                c1, c2, c3 = st.columns(3)
                e_data = c1.date_input("Data", a.data_hora.date(), format="DD/MM/YYYY", key=f"ed_{a.id}")
                e_hora = c2.time_input("Horário", a.data_hora.time().replace(second=0, microsecond=0), step=1800, key=f"eh_{a.id}")
                e_dur = c3.number_input("Duração (min)", min_value=15, step=15, value=int(a.duracao_min or 60), key=f"edu_{a.id}")
                c4, c5, c6 = st.columns(3)
                e_box = c4.selectbox("Box", BOXES, index=BOXES.index(a.box) if a.box in BOXES else 0, key=f"eb_{a.id}")
                e_mec = c5.selectbox("Mecânico", mecs, index=mecs.index(a.mecanico) if a.mecanico in mecs else 0, key=f"em_{a.id}")
                e_st = c6.selectbox("Status", STATUS_AG, index=STATUS_AG.index(a.status) if a.status in STATUS_AG else 0, key=f"es_{a.id}")
                e_obs = st.text_area("Observações", value=a.observacao or "", key=f"eo_{a.id}")
                salvar = btn_form("💾 Salvar", type="primary")
            if salvar:
                novo_ini = dt.datetime.combine(e_data, e_hora)
                conf = conflitos_box(s, e_box, novo_ini, int(e_dur), ignorar_id=a.id) if e_st in ("Agendado", "Em Andamento") else []
                if conf:
                    st.error(f"Conflito com o agendamento #{conf[0].id} ({conf[0].placa}) neste box/horário.")
                else:
                    a.data_hora, a.duracao_min, a.box, a.mecanico, a.status, a.observacao = novo_ini, int(e_dur), e_box, e_mec, e_st, e_obs.strip()
                    s.commit()
                    auditar("EDITAR_AGENDAMENTO", f"#{a.id} → {e_st}")
                    flash("Agendamento atualizado.")
                    st.rerun()

            b1, b2 = st.columns(2)
            with b1:
                veic = s.query(VeiculoModel).filter(VeiculoModel.placa == a.placa).first()
                if veic and a.status in ("Agendado", "Em Andamento"):
                    if btn("🔧 Converter em O.S.", key=f"conv_{a.id}"):
                        o = OrdemServicoModel(veiculo_id=veic.id, mecanico=a.mecanico or SEM_MECANICO, status="Aberta",
                                              defeito=a.observacao or "A diagnosticar (originado de agendamento)",
                                              km_entrada=veic.km or 0)
                        s.add(o)
                        s.flush()
                        recalcular_os(o)
                        a.status = "Em Andamento"
                        s.commit()
                        st.session_state["os_sel"] = o.id
                        auditar("AGENDA_PARA_OS", f"Agendamento #{a.id} → O.S. #{o.id}")
                        flash(f"O.S. #{o.id} criada a partir do agendamento. Acesse **Ordens de Serviço**.")
                        st.rerun()
            with b2:
                if pode("excluir") and confirmar_exclusao("🗑️ Excluir agendamento", f"del_ag_{a.id}"):
                    s.delete(a)
                    s.commit()
                    auditar("EXCLUIR_AGENDAMENTO", f"#{sid}")
                    flash("Agendamento excluído.", "warning")
                    st.rerun()


# ------------------------------------------------------------------ CLIENTES ---
def pagina_clientes():
    cabecalho("Clientes & Garagem", "Cadastro de proprietários e veículos")
    if not pode("clientes"):
        st.error("Seu perfil não tem acesso a este módulo.")
        return
    t1, t2, t3 = st.tabs(["➕ Novo cliente", "🚘 Novo veículo", "📋 Gerenciar"])

    with t1:
        with st.form("form_cliente", clear_on_submit=True):
            c1, c2 = st.columns(2)
            nome = c1.text_input("Nome completo *")
            tel = c2.text_input("Telefone / WhatsApp", placeholder="11999998888")
            c3, c4 = st.columns(2)
            doc = c3.text_input("CPF / CNPJ")
            email = c4.text_input("E-mail")
            end = st.text_input("Endereço")
            ok = btn_form("Salvar cliente", type="primary")
        if ok:
            digitos = so_digitos(tel)
            if not nome.strip():
                st.error("Informe o nome do cliente.")
            else:
                with db() as s:
                    c = ClienteModel(nome=nome.strip(), telefone=digitos or None, documento=doc.strip() or None,
                                     endereco=end.strip() or None, email=email.strip() or None)
                    s.add(c)
                    s.commit()
                    cid = c.id
                auditar("CRIAR_CLIENTE", f"{nome.strip()} (#{cid})")
                flash(f"Cliente **{nome.strip()}** cadastrado (ID {cid}).")
                st.rerun()

    with t2:
        with db() as s:
            clientes = {c.id: f"{c.nome}" + (f" · {c.documento}" if c.documento else "")
                        for c in s.query(ClienteModel).order_by(ClienteModel.nome)}
        if not clientes:
            st.info("Cadastre um cliente primeiro.")
        else:
            with st.form("form_veiculo", clear_on_submit=True):
                cid = st.selectbox("Proprietário *", list(clientes), format_func=lambda i: clientes[i], index=None,
                                   placeholder="Busque pelo nome...")
                c1, c2 = st.columns(2)
                placa = normalizar_placa(c1.text_input("Placa *", placeholder="ABC1D23"))
                modelo = c2.text_input("Modelo / versão *")
                c3, c4, c5 = st.columns(3)
                ano = c3.text_input("Ano")
                cor = c4.text_input("Cor")
                km = c5.number_input("Km atual", min_value=0, step=1000)
                ok = btn_form("Salvar veículo", type="primary")
            if ok:
                if cid is None or not modelo.strip():
                    st.error("Selecione o proprietário e informe o modelo.")
                elif not PLACA_RE.match(placa):
                    st.error("Placa inválida. Use o formato ABC1234 ou ABC1D23.")
                else:
                    with db() as s:
                        if s.query(VeiculoModel).filter(VeiculoModel.placa == placa).first():
                            st.error(f"A placa {placa} já está cadastrada.")
                        else:
                            s.add(VeiculoModel(cliente_id=cid, placa=placa, modelo=modelo.strip(), ano=ano.strip(),
                                               cor=cor.strip(), km=int(km)))
                            s.commit()
                            auditar("CRIAR_VEICULO", f"{placa} - {modelo.strip()}")
                            flash(f"Veículo {modelo.strip()} ({placa}) registrado.")
                            st.rerun()

    with t3:
        busca = st.text_input("Buscar cliente", placeholder="Nome, telefone ou documento", key="cli_busca").strip()
        with db() as s:
            q = s.query(ClienteModel)
            if busca:
                t = f"%{busca}%"
                q = q.filter(ClienteModel.nome.ilike(t) | ClienteModel.telefone.ilike(t) | ClienteModel.documento.ilike(t))
            clientes = q.order_by(ClienteModel.nome).limit(300).all()
            if not clientes:
                st.info("Nenhum cliente encontrado.")
                return
            vcount = dict(s.query(VeiculoModel.cliente_id, func.count(VeiculoModel.id)).group_by(VeiculoModel.cliente_id).all())
            ocount = dict(s.query(VeiculoModel.cliente_id, func.count(OrdemServicoModel.id))
                          .join(OrdemServicoModel, OrdemServicoModel.veiculo_id == VeiculoModel.id)
                          .group_by(VeiculoModel.cliente_id).all())
            tabela(pd.DataFrame([{"ID": c.id, "Nome": c.nome, "Telefone": c.telefone or "—", "Documento": c.documento or "—",
                                  "Veículos": vcount.get(c.id, 0), "O.S.": ocount.get(c.id, 0)} for c in clientes]), height=240)
            rot = {c.id: f"#{c.id} · {c.nome}" for c in clientes}
            cid = st.selectbox("Selecione o cliente", list(rot), format_func=lambda i: rot[i], key="cli_sel")
            c = s.get(ClienteModel, cid)

            with st.form(f"form_cli_{c.id}"):
                c1, c2 = st.columns(2)
                e_nome = c1.text_input("Nome", value=c.nome, key=f"cn_{c.id}")
                e_tel = c2.text_input("Telefone", value=c.telefone or "", key=f"ct_{c.id}")
                c3, c4 = st.columns(2)
                e_doc = c3.text_input("Documento", value=c.documento or "", key=f"cd_{c.id}")
                e_mail = c4.text_input("E-mail", value=c.email or "", key=f"cm_{c.id}")
                e_end = st.text_input("Endereço", value=c.endereco or "", key=f"ce_{c.id}")
                salvar = btn_form("💾 Atualizar cliente", type="primary")
            if salvar:
                if not e_nome.strip():
                    st.error("O nome não pode ficar vazio.")
                else:
                    c.nome, c.telefone, c.documento = e_nome.strip(), so_digitos(e_tel) or None, e_doc.strip() or None
                    c.email, c.endereco = e_mail.strip() or None, e_end.strip() or None
                    s.commit()
                    auditar("EDITAR_CLIENTE", f"#{c.id}")
                    flash("Cliente atualizado.")
                    st.rerun()

            st.markdown("##### Veículos do cliente")
            if not c.veiculos:
                st.caption("Nenhum veículo vinculado.")
            for v in c.veiculos:
                n_os = s.query(func.count(OrdemServicoModel.id)).filter(OrdemServicoModel.veiculo_id == v.id).scalar()
                with st.expander(f"{v.placa} · {v.modelo} ({v.ano or '—'}) · {n_os} O.S."):
                    with st.form(f"form_v_{v.id}"):
                        c1, c2, c3 = st.columns(3)
                        ev_placa = normalizar_placa(c1.text_input("Placa", value=v.placa, key=f"vp_{v.id}"))
                        ev_mod = c2.text_input("Modelo", value=v.modelo, key=f"vm_{v.id}")
                        ev_ano = c3.text_input("Ano", value=v.ano or "", key=f"va_{v.id}")
                        c4, c5 = st.columns(2)
                        ev_cor = c4.text_input("Cor", value=v.cor or "", key=f"vc_{v.id}")
                        ev_km = c5.number_input("Km", min_value=0, value=int(v.km or 0), step=1000, key=f"vk_{v.id}")
                        salvar_v = btn_form("💾 Atualizar veículo")
                    if salvar_v:
                        dup = s.query(VeiculoModel).filter(VeiculoModel.placa == ev_placa, VeiculoModel.id != v.id).first()
                        if not PLACA_RE.match(ev_placa):
                            st.error("Placa inválida.")
                        elif dup:
                            st.error("Já existe outro veículo com esta placa.")
                        else:
                            v.placa, v.modelo, v.ano, v.cor, v.km = ev_placa, ev_mod.strip(), ev_ano.strip(), ev_cor.strip(), int(ev_km)
                            s.commit()
                            auditar("EDITAR_VEICULO", f"{v.placa}")
                            flash("Veículo atualizado.")
                            st.rerun()
                    if pode("excluir"):
                        if n_os:
                            st.caption("Veículo com histórico de O.S. não pode ser excluído.")
                        elif confirmar_exclusao("🗑️ Excluir veículo", f"del_v_{v.id}"):
                            s.delete(v)
                            s.commit()
                            auditar("EXCLUIR_VEICULO", v.placa)
                            flash("Veículo excluído.", "warning")
                            st.rerun()

            if pode("excluir"):
                st.markdown("##### Zona de risco")
                if ocount.get(c.id, 0):
                    st.caption("Clientes com histórico de O.S. não podem ser excluídos.")
                elif confirmar_exclusao("🗑️ Excluir cliente e veículos", f"del_c_{c.id}",
                                        "O cliente e todos os veículos vinculados serão removidos."):
                    s.delete(c)
                    s.commit()
                    auditar("EXCLUIR_CLIENTE", f"#{cid}")
                    flash("Cliente excluído.", "warning")
                    st.rerun()


# ------------------------------------------------------------------ ESTOQUE ----
def status_estoque(p) -> str:
    if (p.quantidade or 0) <= 0:
        return "⛔ Zerado"
    if p.quantidade <= (p.estoque_minimo or 0):
        return "⚠️ Baixo"
    return "✅ OK"


def pagina_estoque():
    cabecalho("Almoxarifado & Peças", "Inventário, movimentações e alertas de reposição")
    editar = pode("estoque_editar")
    abas = ["📦 Inventário", "📜 Movimentações"] + (["➕ Cadastrar peça"] if editar else [])
    tabs = st.tabs(abas)

    with tabs[0]:
        with db() as s:
            pecas = s.query(PecaModel).order_by(PecaModel.nome).all()
            if not pecas:
                st.info("Nenhuma peça cadastrada.")
            else:
                m = st.columns(4)
                m[0].metric("Itens cadastrados", len(pecas))
                m[1].metric("Unidades em estoque", sum(p.quantidade or 0 for p in pecas))
                m[2].metric("Valor a preço de custo", brl(sum((p.quantidade or 0) * (p.preco_custo or 0) for p in pecas)))
                m[3].metric("Abaixo do mínimo", sum(1 for p in pecas if (p.quantidade or 0) <= (p.estoque_minimo or 0)))
                f1, f2 = st.columns([3, 1])
                busca = f1.text_input("Buscar peça", placeholder="Nome ou código", key="est_busca").strip().lower()
                so_baixo = f2.toggle("Só em alerta", key="est_baixo")
                filtradas = [p for p in pecas if (not busca or busca in (p.nome or "").lower() or busca in (p.codigo or "").lower())
                             and (not so_baixo or (p.quantidade or 0) <= (p.estoque_minimo or 0))]
                tabela(pd.DataFrame([{
                    "Código": p.codigo, "Peça": p.nome, "Qtd": p.quantidade, "Mínimo": p.estoque_minimo,
                    "Situação": status_estoque(p), "Custo": p.preco_custo, "Venda": p.preco_venda,
                    "Margem %": ((p.preco_venda - p.preco_custo) / p.preco_venda * 100) if p.preco_venda else 0.0,
                } for p in filtradas]), column_config={
                    "Custo": st.column_config.NumberColumn(format="R$ %.2f"),
                    "Venda": st.column_config.NumberColumn(format="R$ %.2f"),
                    "Margem %": st.column_config.NumberColumn(format="%.1f%%"),
                }, height=300)

                if editar and filtradas:
                    rot = {p.id: f"{p.codigo or 's/ref'} · {p.nome} (qtd {p.quantidade})" for p in filtradas}
                    pid = st.selectbox("Selecione uma peça para editar ou movimentar", list(rot),
                                       format_func=lambda i: rot[i], key="est_sel")
                    p = s.get(PecaModel, pid)
                    usuario = st.session_state["usuario"]
                    c1, c2 = st.columns(2)
                    with c1:
                        st.markdown("**Dados da peça**")
                        with st.form(f"form_peca_{p.id}"):
                            e_nome = st.text_input("Nome", value=p.nome, key=f"pn_{p.id}")
                            e_cod = st.text_input("Código / referência", value=p.codigo or "", key=f"pc_{p.id}")
                            e_min = st.number_input("Estoque mínimo", min_value=0, value=int(p.estoque_minimo or 0), key=f"pm_{p.id}")
                            e_custo = st.number_input("Custo (R$)", min_value=0.0, value=float(p.preco_custo or 0), step=5.0, key=f"pcu_{p.id}")
                            e_venda = st.number_input("Venda (R$)", min_value=0.0, value=float(p.preco_venda or 0), step=5.0, key=f"pv_{p.id}")
                            salvar = btn_form("💾 Salvar dados", type="primary")
                        if salvar:
                            p.nome, p.codigo, p.estoque_minimo = e_nome.strip(), e_cod.strip() or None, int(e_min)
                            p.preco_custo, p.preco_venda = e_custo, e_venda
                            s.commit()
                            auditar("EDITAR_PECA", f"#{p.id} {p.nome}")
                            flash("Peça atualizada.")
                            st.rerun()
                    with c2:
                        st.markdown("**Movimentar estoque**")
                        with st.form(f"form_mov_{p.id}", clear_on_submit=True):
                            tipo = st.selectbox("Tipo", ["Entrada (compra/reposição)", "Saída manual", "Ajuste de inventário"], key=f"mt_{p.id}")
                            qtd = st.number_input("Quantidade", min_value=0, step=1, key=f"mq_{p.id}")
                            motivo = st.text_input("Motivo / nota fiscal", key=f"mmo_{p.id}")
                            mov_ok = btn_form("Registrar movimentação")
                        if mov_ok:
                            if tipo.startswith("Entrada") or tipo.startswith("Saída"):
                                if qtd <= 0:
                                    st.error("Informe uma quantidade maior que zero.")
                                elif tipo.startswith("Saída") and qtd > (p.quantidade or 0):
                                    st.error(f"Saldo insuficiente (disponível: {p.quantidade}).")
                                else:
                                    if tipo.startswith("Entrada"):
                                        p.quantidade += int(qtd)
                                        _mov(s, p.id, "ENTRADA", int(qtd), motivo or "Entrada manual", usuario)
                                    else:
                                        p.quantidade -= int(qtd)
                                        _mov(s, p.id, "SAÍDA", int(qtd), motivo or "Saída manual", usuario)
                                    s.commit()
                                    auditar("MOVIMENTO_ESTOQUE", f"{p.nome}: {tipo} {qtd}")
                                    flash("Movimentação registrada.")
                                    st.rerun()
                            else:
                                dif = int(qtd) - (p.quantidade or 0)
                                p.quantidade = int(qtd)
                                _mov(s, p.id, "AJUSTE", dif, motivo or "Ajuste de inventário", usuario)
                                s.commit()
                                auditar("AJUSTE_ESTOQUE", f"{p.nome}: nova qtd {qtd}")
                                flash("Inventário ajustado.")
                                st.rerun()

    with tabs[1]:
        with db() as s:
            movs = (s.query(MovimentoEstoqueModel).options(joinedload(MovimentoEstoqueModel.peca))
                    .order_by(MovimentoEstoqueModel.id.desc()).limit(300).all())
            if movs:
                tabela(pd.DataFrame([{"Data": m.timestamp, "Peça": m.peca.nome if m.peca else "—", "Tipo": m.tipo,
                                      "Qtd": m.quantidade, "Motivo": m.motivo, "Usuário": m.usuario} for m in movs]),
                       column_config={"Data": st.column_config.DatetimeColumn(format="DD/MM/YYYY HH:mm")}, height=420)
            else:
                st.info("Nenhuma movimentação registrada ainda.")

    if editar:
        with tabs[2]:
            with st.form("form_nova_peca", clear_on_submit=True):
                c1, c2 = st.columns(2)
                nome = c1.text_input("Descrição da peça / kit *")
                cod = c2.text_input("Código / referência")
                c3, c4, c5, c6 = st.columns(4)
                qtd = c3.number_input("Qtd inicial", min_value=0, step=1)
                mini = c4.number_input("Estoque mínimo", min_value=0, value=3, step=1)
                custo = c5.number_input("Custo (R$)", min_value=0.0, step=5.0)
                venda = c6.number_input("Venda (R$)", min_value=0.0, step=5.0)
                ok = btn_form("Cadastrar peça", type="primary")
            if ok:
                if not nome.strip():
                    st.error("Informe a descrição da peça.")
                else:
                    with db() as s:
                        codigo = cod.strip() or f"PC-{(s.query(func.max(PecaModel.id)).scalar() or 0) + 1:04d}"
                        p = PecaModel(nome=nome.strip(), codigo=codigo, quantidade=int(qtd), estoque_minimo=int(mini),
                                      preco_custo=custo, preco_venda=venda)
                        s.add(p)
                        s.flush()
                        if qtd:
                            _mov(s, p.id, "ENTRADA", int(qtd), "Estoque inicial", st.session_state["usuario"])
                        s.commit()
                        auditar("CRIAR_PECA", f"{codigo} - {nome.strip()}")
                        flash(f"Peça cadastrada com o código **{codigo}**.")
                        st.rerun()


# ------------------------------------------------------------------ PRONTUÁRIO -
def pagina_prontuario():
    cabecalho("Prontuário do Veículo", "Histórico completo de manutenções")
    with db() as s:
        veics = mapa_veiculos(s)
    if not veics:
        st.info("Nenhum veículo cadastrado.")
        return
    vid = st.selectbox("Veículo", list(veics), format_func=lambda i: veics[i], index=None,
                       placeholder="Digite a placa para consultar...")
    if vid is None:
        return
    with db() as s:
        v = (s.query(VeiculoModel)
             .options(joinedload(VeiculoModel.dono),
                      joinedload(VeiculoModel.ordens_servico).joinedload(OrdemServicoModel.itens))
             .get(vid))
        dono = v.dono
        c = st.columns(4)
        c[0].metric("Placa", v.placa)
        c[1].metric("Veículo", f"{v.modelo}")
        c[2].metric("Ano / Cor", f"{v.ano or '—'} / {v.cor or '—'}")
        c[3].metric("Km cadastrado", f"{v.km or 0:,}".replace(",", "."))
        st.markdown(f"**Proprietário:** {dono.nome if dono else 'Sem proprietário'} · "
                    f"**Tel:** {dono.telefone if dono and dono.telefone else 'Não informado'}")
        ordens = sorted(v.ordens_servico, key=lambda x: x.id, reverse=True)
        concl = [o for o in ordens if o.status == "Concluída"]
        k = st.columns(4)
        k[0].metric("O.S. no histórico", len(ordens))
        k[1].metric("Total investido", brl(sum(o.valor_total or 0 for o in concl)))
        k[2].metric("Ticket médio", brl(sum(o.valor_total or 0 for o in concl) / len(concl)) if concl else "—")
        ultima = max((o.data_conclusao or o.data_abertura for o in concl), default=None)
        k[3].metric("Última visita", ultima.strftime("%d/%m/%Y") if ultima else "—")
        st.markdown("#### Linha do tempo de manutenções")
        if not ordens:
            st.warning("Nenhuma O.S. registrada para este veículo.")
        for o in ordens:
            with st.expander(f"{STATUS_ICON.get(o.status, '')} O.S. #{o.id} · {o.data_abertura.strftime('%d/%m/%Y')} · "
                             f"{o.status} · {brl(o.valor_total)} · Pgto: {o.forma_pagamento}"):
                st.markdown(f"**Mecânico:** {o.mecanico} · **Km:** {o.km_entrada or 0}  \n**Defeito:** {o.defeito}")
                if o.laudo:
                    st.markdown(f"**Laudo:** {o.laudo}")
                if o.itens:
                    tabela(pd.DataFrame([{"Item": i.descricao, "Qtd": i.quantidade, "Unitário": i.preco_unit,
                                          "Total": (i.quantidade or 0) * (i.preco_unit or 0)} for i in o.itens]),
                           column_config={"Unitário": st.column_config.NumberColumn(format="R$ %.2f"),
                                          "Total": st.column_config.NumberColumn(format="R$ %.2f")})
                st.caption(f"Mão de obra {brl(o.mao_de_obra)} · Peças {brl(o.pecas_valor)} · "
                           f"Desconto {brl(o.desconto)} · **Total {brl(o.valor_total)}**")


# ------------------------------------------------------------------ GESTÃO / FINANÇAS --
def _dados_periodo(s, d1, d2):
    ini = dt.datetime.combine(d1, dt.time.min)
    fim = dt.datetime.combine(d2, dt.time.max)
    ref = func.coalesce(OrdemServicoModel.data_conclusao, OrdemServicoModel.data_abertura)
    concl = (s.query(OrdemServicoModel)
             .options(joinedload(OrdemServicoModel.itens).joinedload(OrdemServicoItemModel.peca))
             .filter(OrdemServicoModel.status == "Concluída", ref >= ini, ref <= fim).all())
    todas = (s.query(OrdemServicoModel)
             .filter(OrdemServicoModel.data_abertura >= ini, OrdemServicoModel.data_abertura <= fim).all())
    return concl, todas


def gestao_financas():
    st.markdown("### 💳 Controle Financeiro & Formas de Pagamento")
    st.caption("Acompanhamento de recebimentos por Pix, Dinheiro, Cartões e A Prazo.")
    d1, d2 = filtro_periodo("fin_periodo")
    with db() as s:
        concl, _ = _dados_periodo(s, d1, d2)
        linhas = []
        for o in concl:
            linhas.append({
                "os": o.id,
                "data": (o.data_conclusao or o.data_abertura),
                "pagamento": o.forma_pagamento or "A definir",
                "total": o.valor_total or 0.0
            })
    df = pd.DataFrame(linhas)
    if df.empty:
        st.info("Nenhuma O.S. concluída no período para compilar as finanças.")
        return

    fat_total = df["total"].sum()
    por_pgto = df.groupby("pagamento", as_index=False)["total"].sum().sort_values("total", ascending=False)

    m = st.columns(3)
    m[0].metric("Recebimento Total no Período", brl(fat_total))
    m[1].metric("Formas de Pagamento Utilizadas", len(por_pgto))
    m[2].metric("Média por O.S.", brl(fat_total / len(df)) if len(df) else "—")

    st.markdown("#### Faturamento por Forma de Pagamento")
    c1, c2 = st.columns(2)
    with c1:
        tabela(por_pgto.rename(columns={"pagamento": "Forma de Pagamento", "total": "Total Arrecadado"}),
               column_config={"Total Arrecadado": st.column_config.NumberColumn(format="R$ %.2f")})
    with c2:
        if PLOTLY_DISPONIVEL:
            fig = px.pie(por_pgto, values="total", names="pagamento", hole=0.4,
                         title="Distribuição por Forma de Pagamento", color_discrete_sequence=CORES)
            grafico(estilizar(fig, altura=300))


def gestao_bi():
    d1, d2 = filtro_periodo("bi_periodo")
    with db() as s:
        concl, todas = _dados_periodo(s, d1, d2)
        linhas = []
        for o in concl:
            custo = sum((i.quantidade or 0) * (i.peca.preco_custo or 0) for i in o.itens if i.peca)
            linhas.append({"data": (o.data_conclusao or o.data_abertura).date(), "mecanico": o.mecanico,
                           "total": o.valor_total or 0.0, "mao": o.mao_de_obra or 0.0, "pecas": o.pecas_valor or 0.0,
                           "desconto": o.desconto or 0.0, "custo": custo})
        itens_vendidos: dict[str, int] = {}
        for o in concl:
            for i in o.itens:
                itens_vendidos[i.descricao] = itens_vendidos.get(i.descricao, 0) + (i.quantidade or 0)
        status_cont = pd.Series([o.status for o in todas]).value_counts() if todas else pd.Series(dtype=int)

    df = pd.DataFrame(linhas)
    fat = df["total"].sum() if not df.empty else 0.0
    lucro = (df["total"] - df["custo"]).sum() if not df.empty else 0.0
    m = st.columns(5)
    m[0].metric("Faturamento", brl(fat))
    m[1].metric("Lucro estimado", brl(lucro))
    m[2].metric("O.S. concluídas", len(concl))
    m[3].metric("Ticket médio", brl(fat / len(concl)) if concl else "—")
    m[4].metric("Descontos", brl(df["desconto"].sum() if not df.empty else 0))
    if df.empty:
        st.info("Nenhuma O.S. concluída no período selecionado.")
        return

    diario = df.groupby("data", as_index=False)["total"].sum()
    mec = df.groupby("mecanico", as_index=False)["total"].sum().sort_values("total", ascending=False)
    mix = pd.DataFrame({"Origem": ["Mão de obra", "Peças"], "Valor": [df["mao"].sum(), df["pecas"].sum()]})
    if PLOTLY_DISPONIVEL:
        c1, c2 = st.columns(2)
        with c1:
            f = px.bar(diario, x="data", y="total", title="Faturamento diário", color_discrete_sequence=[CORES[0]])
            f.update_layout(xaxis_title=None, yaxis_title="R$")
            grafico(estilizar(f))
        with c2:
            f = px.pie(mix, values="Valor", names="Origem", hole=0.5, title="Origem do faturamento", color_discrete_sequence=CORES)
            grafico(estilizar(f))
        c3, c4 = st.columns(2)
        with c3:
            f = px.bar(mec, x="total", y="mecanico", orientation="h", title="Faturamento por mecânico", color_discrete_sequence=[CORES[1]])
            f.update_layout(xaxis_title="R$", yaxis_title=None, yaxis=dict(autorange="reversed"))
            grafico(estilizar(f))
        with c4:
            if len(status_cont):
                sc = status_cont.reset_index()
                sc.columns = ["Status", "Quantidade"]
                f = px.pie(sc, values="Quantidade", names="Status", hole=0.5, title="O.S. abertas no período por status",
                           color_discrete_sequence=CORES)
                grafico(estilizar(f))
    if itens_vendidos:
        st.markdown("##### Itens mais utilizados")
        top = sorted(itens_vendidos.items(), key=lambda x: x[1], reverse=True)[:10]
        tabela(pd.DataFrame(top, columns=["Item", "Quantidade"]))


def gestao_comissoes():
    d1, d2 = filtro_periodo("com_periodo")
    with db() as s:
        pct = float(cfg_get(s).get("comissao_pct", "20"))
        concl, _ = _dados_periodo(s, d1, d2)
        dados: dict[str, dict] = {}
        for o in concl:
            r = dados.setdefault(o.mecanico or SEM_MECANICO, {"os": 0, "mao": 0.0})
            r["os"] += 1
            r["mao"] += o.mao_de_obra or 0.0
    if not dados:
        st.info("Nenhuma O.S. concluída no período.")
        return
    df = pd.DataFrame([{"Mecânico": k, "O.S. concluídas": v["os"], "Mão de obra": v["mao"],
                        f"Comissão ({pct:g}%)": v["mao"] * pct / 100} for k, v in dados.items()]).sort_values("Mão de obra", ascending=False)
    st.metric("Total de comissões no período", brl(df.iloc[:, 3].sum()))
    tabela(df, column_config={"Mão de obra": st.column_config.NumberColumn(format="R$ %.2f"),
                              df.columns[3]: st.column_config.NumberColumn(format="R$ %.2f")})
    btn_download("📊 Exportar comissões (CSV)", df.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig"),
                 file_name=f"comissoes_{d1}_{d2}.csv", mime="text/csv")


def gestao_usuarios():
    with db() as s:
        usuarios = s.query(UsuarioModel).order_by(UsuarioModel.usuario).all()
        tabela(pd.DataFrame([{"Usuário": u.usuario, "Perfil": u.perfil, "Ativo": "Sim" if u.ativo != 0 else "Não",
                              "Troca de senha pendente": "Sim" if u.trocar_senha else "Não",
                              "Último login": u.ultimo_login} for u in usuarios]),
               column_config={"Último login": st.column_config.DatetimeColumn(format="DD/MM/YYYY HH:mm")})

        st.markdown("##### Novo usuário")
        with st.form("form_novo_user", clear_on_submit=True):
            c1, c2, c3 = st.columns(3)
            nome = c1.text_input("Usuário", help="3 a 30 caracteres.").strip().lower()
            perfil = c2.selectbox("Perfil", PERFIS)
            senha = c3.text_input("Senha temporária", type="password")
            ok = btn_form("Criar usuário", type="primary")
        if ok:
            erro = validar_senha_nova(senha)
            if not USUARIO_RE.match(nome):
                st.error("Nome de usuário inválido.")
            elif erro:
                st.error(erro)
            else:
                s.add(UsuarioModel(usuario=nome, senha_hash=hash_senha(senha), perfil=perfil, ativo=1, trocar_senha=1))
                s.commit()
                auditar("CRIAR_USUARIO", f"{nome} ({perfil})")
                flash(f"Usuário **{nome}** criado.")
                st.rerun()


def gestao_auditoria():
    with db() as s:
        logs = s.query(AuditLogModel).order_by(AuditLogModel.id.desc()).limit(300).all()
        if logs:
            tabela(pd.DataFrame([{"Data": l.timestamp, "Usuário": l.usuario, "Ação": l.acao, "Detalhes": l.detalhes} for l in logs]),
                   column_config={"Data": st.column_config.DatetimeColumn(format="DD/MM/YYYY HH:mm:ss")}, height=480)
        else:
            st.info("Nenhum registro de auditoria.")


def gestao_config():
    with db() as s:
        cfg = cfg_get(s)
        with st.form("form_cfg"):
            nome = st.text_input("Nome da oficina", value=cfg["oficina_nome"])
            c1, c2 = st.columns(2)
            cnpj = c1.text_input("CNPJ", value=cfg["oficina_cnpj"])
            tel = c2.text_input("Telefone", value=cfg["oficina_telefone"])
            end = st.text_input("Endereço", value=cfg["oficina_endereco"])
            com = st.number_input("Comissão dos mecânicos (%)", min_value=0.0, max_value=100.0,
                                  value=float(cfg["comissao_pct"] or 20), step=1.0)
            ok = btn_form("💾 Salvar configurações", type="primary")
        if ok:
            for k, v in {"oficina_nome": nome.strip() or "LOJA Performance", "oficina_cnpj": cnpj.strip(),
                         "oficina_telefone": tel.strip(), "oficina_endereco": end.strip(), "comissao_pct": str(com)}.items():
                cfg_set(s, k, v)
            s.commit()
            auditar("ALTERAR_CONFIG", "Configurações da oficina")
            flash("Configurações salvas.")
            st.rerun()


def gestao_backup():
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("##### Backup & Exportação")
        if btn("Gerar backup (.db)", key="gen_bkp"):
            st.session_state["bkp"] = (backup_bytes(), dt.datetime.now().strftime("%Y%m%d_%H%M%S"))
            auditar("BACKUP", "Backup gerado")
        if "bkp" in st.session_state:
            dados, carimbo = st.session_state["bkp"]
            btn_download("💾 Baixar arquivo .db", dados, file_name=f"oficina_backup_{carimbo}.db",
                         mime="application/x-sqlite3", key="dl_bkp")

        st.markdown("---")
        st.markdown("##### 📥 Importar Dados do SHoficina")
        st.caption("Faça o upload dos arquivos exportados do seu SHoficina (em formato CSV ou Excel) para migrar seus cadastros.")
        tipo_imp = st.selectbox("O que você está importando?", ["clientes", "veiculos", "pecas"],
                                format_func=lambda x: {"clientes": "Clientes", "veiculos": "Veículos", "pecas": "Peças / Estoque"}[x])
        arq_sub = st.file_uploader("Arquivo CSV ou Excel do SHoficina", type=["csv", "xlsx", "xls"])
        if arq_sub and btn("Executar Importação"):
            try:
                if arq_sub.name.endswith(".csv"):
                    df_imp = pd.read_csv(arq_sub, sep=None, engine="python")
                else:
                    df_imp = pd.read_excel(arq_sub)
                ins, ign = importar_dados_shoficina(df_imp, tipo_imp)
                auditar("IMPORTACAO_SHOFICINA", f"Tipo: {tipo_imp} | Inseridos: {ins} | Ignorados: {ign}")
                st.success(f"Importação concluída! {ins} registros inseridos ({ign} ignorados/duplicados).")
            except Exception as e:
                st.error(f"Erro ao processar arquivo: {e}")

    with c2:
        st.markdown("##### Exportar Relatórios Atuais (CSV)")
        with db() as s:
            ordens = os_query(s).order_by(OrdemServicoModel.id).all()
            df_os = pd.DataFrame([{
                "ID": o.id, "Abertura": fmt_dt(o.data_abertura), "Placa": o.veiculo.placa if o.veiculo else "",
                "Modelo": o.veiculo.modelo if o.veiculo else "", "Cliente": o.veiculo.dono.nome if o.veiculo and o.veiculo.dono else "",
                "Mecânico": o.mecanico, "Total": o.valor_total, "Pagamento": o.forma_pagamento, "Status": o.status} for o in ordens])
            df_cli = pd.DataFrame([{"ID": c.id, "Nome": c.nome, "Telefone": c.telefone, "Documento": c.documento} for c in s.query(ClienteModel).all()])
            df_pec = pd.DataFrame([{"Código": p.codigo, "Peça": p.nome, "Qtd": p.quantidade, "Venda": p.preco_venda} for p in s.query(PecaModel).all()])
        for rotulo, df, arq in [("📊 Ordens de serviço", df_os, "ordens_servico.csv"),
                                ("👤 Clientes", df_cli, "clientes.csv"), ("📦 Estoque", df_pec, "estoque.csv")]:
            btn_download(rotulo, df.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig"),
                         file_name=arq, mime="text/csv", key=f"exp_{arq}")


def pagina_gestao():
    cabecalho("Gestão Executiva", "Finanças, BI, comissões, usuários, auditoria e migração do SHoficina")
    if st.session_state["perfil"] != "Administrador":
        st.error("Acesso exclusivo para administradores.")
        return
    abas = st.tabs(["💳 Finanças", "📈 BI Financeiro", "💰 Comissões", "👥 Usuários", "🕵️ Auditoria", "⚙️ Configurações", "💾 Backup & Migração"])
    for aba, fn in zip(abas, [gestao_financas, gestao_bi, gestao_comissoes, gestao_usuarios, gestao_auditoria, gestao_config, gestao_backup]):
        with aba:
            fn()


# ------------------------------------------------------------------ CONTA ------
def pagina_conta():
    cabecalho("Minha Conta", "Segurança e dados de acesso")
    st.markdown(f"**Usuário:** `{st.session_state['usuario']}` · **Perfil:** `{st.session_state['perfil']}`")
    with st.form("form_conta", clear_on_submit=True):
        atual = st.text_input("Senha atual", type="password")
        nova = st.text_input("Nova senha", type="password", help="Mínimo de 8 caracteres, com letras e números.")
        conf = st.text_input("Confirmar nova senha", type="password")
        ok = btn_form("Alterar senha", type="primary")
    if ok:
        if nova != conf:
            st.error("A confirmação não confere com a nova senha.")
        else:
            sucesso, msg = alterar_senha(st.session_state["uid"], nova, atual)
            if sucesso:
                auditar("TROCA_SENHA", "Troca voluntária")
                st.success(msg)
            else:
                st.error(msg)


# ==============================================================================
# 8. APLICAÇÃO PRINCIPAL
# ==============================================================================
iniciar_banco()
st.session_state.setdefault("autenticado", False)

if not st.session_state["autenticado"]:
    tela_login()
    st.stop()

if st.session_state.get("trocar_senha"):
    tela_troca_obrigatoria()
    st.stop()

MENUS = {
    "🏁 Painel": (pagina_painel, set(PERFIS)),
    "🔧 Ordens de Serviço": (pagina_os, set(PERFIS)),
    "📅 Agenda & Box": (pagina_agenda, set(PERFIS)),
    "🚘 Clientes & Garagem": (pagina_clientes, PERMISSOES["clientes"]),
    "📦 Almoxarifado": (pagina_estoque, set(PERFIS)),
    "🔍 Prontuário": (pagina_prontuario, set(PERFIS)),
    "📊 Gestão & Finanças": (pagina_gestao, {"Administrador"}),
    "👤 Minha Conta": (pagina_conta, set(PERFIS)),
}
perfil = st.session_state["perfil"]
permitidos = [k for k, (_, perfis) in MENUS.items() if perfil in perfis]

with st.sidebar:
    with db() as _s:
        _nome_oficina = cfg_get(_s)["oficina_nome"]
        _baixos = _s.query(func.count(PecaModel.id)).filter(PecaModel.quantidade <= PecaModel.estoque_minimo).scalar()
    st.markdown(f"<div class='brand'>🏎️ {esc(_nome_oficina)}<small>ENTERPRISE · v{APP_VERSAO}</small></div>", unsafe_allow_html=True)
    st.markdown(f"<br>**{esc(st.session_state['usuario'])}**  \n<span class='badge'>{esc(perfil)}</span>", unsafe_allow_html=True)
    st.divider()
    escolha = st.radio("Navegação", permitidos, label_visibility="collapsed")
    if _baixos:
        st.caption(f"⚠️ {_baixos} peça(s) em alerta de estoque")
    st.divider()
    if btn("Encerrar sessão"):
        auditar("LOGOUT", "")
        st.session_state.clear()
        st.rerun()

MENUS[escolha][0]()
