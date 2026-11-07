import streamlit as st
import pandas as pd
import datetime
import hashlib
import sqlite3
import urllib.parse
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, ForeignKey, Text
from sqlalchemy.orm import declarative_base, sessionmaker, relationship, scoped_session, joinedload
import io

# --- TENTATIVA DE IMPORTAÇÃO DE BIBLIOGRAFIAS OPCIONAIS ---
try:
    import plotly.express as px
    import plotly.graph_objects as go
    PLOTLY_DISPONIVEL = True
except ImportError:
    PLOTLY_DISPONIVEL = False

try:
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors
    REPORTLAB_DISPONIVEL = True
except ImportError:
    REPORTLAB_DISPONIVEL = False

# ==============================================================================
# 1. CONFIGURAÇÃO DA PÁGINA & ENGINE CSS (DARK COCKPIT ENTERPRISE)
# ==============================================================================
st.set_page_config(
    page_title="LOJA Performance Enterprise",
    page_icon="🏎️",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
    <style>
    html, body, [data-testid="stAppViewContainer"], [data-testid="stHeader"], .stApp {
        background-color: #080A0F !important;
        color: #E2E8F0 !important;
        font-family: 'Segoe UI', Roboto, Helvetica, Arial, sans-serif !important;
    }
    [data-testid="stHeader"] { background-color: rgba(8, 10, 15, 0.95) !important; }
    [data-testid="stSidebar"], [data-testid="stSidebarContent"] {
        background-color: #11141C !important;
        border-right: 1px solid #1E2433 !important;
    }
    [data-testid="stSidebar"] * { color: #CBD5E1 !important; }
    div[data-baseweb="input"], div[data-baseweb="textarea"], input[type="text"], input[type="password"], input[type="number"], textarea {
        background-color: #171C26 !important;
        color: #FFFFFF !important;
        -webkit-text-fill-color: #FFFFFF !important;
        border: 1px solid #2B3448 !important;
        border-radius: 6px !important;
    }
    div[data-testid="stForm"] {
        background-color: #11141C !important;
        border: 1px solid #1E2433 !important;
        border-radius: 12px !important;
        padding: 24px !important;
    }
    label, [data-testid="stWidgetLabel"] p, .stMarkdown p {
        color: #94A3B8 !important;
        font-weight: 600 !important;
        text-transform: uppercase !important;
        font-size: 0.82rem !important;
    }
    div.stButton > button, div[data-testid="stFormSubmitButton"] > button {
        background: linear-gradient(135deg, #E62E2D 0%, #A31212 100%) !important;
        color: #FFFFFF !important;
        font-weight: 800 !important;
        text-transform: uppercase !important;
        border: none !important;
        border-radius: 6px !important;
        padding: 10px 20px !important;
        box-shadow: 0 4px 15px rgba(230, 46, 45, 0.4) !important;
    }
    div.stButton > button:hover {
        background: linear-gradient(135deg, #FF3B30 0%, #C01919 100%) !important;
        transform: translateY(-2px);
    }
    .header-title {
        color: #FF3B30 !important;
        font-weight: 900;
        font-size: 2.2rem;
        letter-spacing: -0.5px;
    }
    .sub-title {
        color: #FF9500 !important;
        font-weight: 700;
        font-size: 1.1rem;
        margin-bottom: 15px;
    }
    .btn-whatsapp {
        display: inline-block;
        background-color: #25D366;
        color: white !important;
        font-weight: bold;
        padding: 8px 16px;
        border-radius: 6px;
        text-decoration: none;
        text-align: center;
    }
    .btn-whatsapp:hover { background-color: #1EBE5D; }
    </style>
""", unsafe_allow_html=True)

# ==============================================================================
# 2. MODELOS DE DADOS (SQLALCHEMY ORM)
# ==============================================================================
Base = declarative_base()
DB_URL = "sqlite:///oficina_enterprise.db"
engine = create_engine(DB_URL, connect_args={"check_same_thread": False})
SessionLocal = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))

class UsuarioModel(Base):
    __tablename__ = "usuarios"
    id = Column(Integer, primary_key=True, index=True)
    usuario = Column(String(50), unique=True, nullable=False)
    senha_hash = Column(String(64), nullable=False)
    perfil = Column(String(20), nullable=False)

class ClienteModel(Base):
    __tablename__ = "clientes"
    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String(100), nullable=False)
    telefone = Column(String(30))
    documento = Column(String(30))
    endereco = Column(String(200))
    veiculos = relationship("VeiculoModel", back_populates="dono", cascade="all, delete-orphan")

class VeiculoModel(Base):
    __tablename__ = "veiculos"
    id = Column(Integer, primary_key=True, index=True)
    cliente_id = Column(Integer, ForeignKey("clientes.id"), nullable=False)
    placa = Column(String(10), unique=True, nullable=False, index=True)
    modelo = Column(String(100), nullable=False)
    ano = Column(String(10))
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
    data_abertura = Column(DateTime, default=datetime.datetime.now)
    veiculo = relationship("VeiculoModel", back_populates="ordens_servico")

class AgendamentoModel(Base):
    __tablename__ = "agendamentos"
    id = Column(Integer, primary_key=True, index=True)
    placa = Column(String(10), nullable=False)
    cliente_nome = Column(String(100), nullable=False)
    box = Column(String(20), nullable=False)
    data_hora = Column(DateTime, nullable=False)
    mecanico = Column(String(50))
    status = Column(String(20), default="Agendado")

class AuditLogModel(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True, index=True)
    usuario = Column(String(50), nullable=False)
    acao = Column(String(100), nullable=False)
    detalhes = Column(Text)
    timestamp = Column(DateTime, default=datetime.datetime.now)

def inicializar_banco():
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        if session.query(UsuarioModel).count() == 0:
            senha_admin = hashlib.sha256("admin123".encode()).hexdigest()
            session.add(UsuarioModel(usuario="admin", senha_hash=senha_admin, perfil="Administrador"))
            session.add(UsuarioModel(usuario="mecanico1", senha_hash=senha_admin, perfil="Mecânico"))
            session.add(UsuarioModel(usuario="recepcao", senha_hash=senha_admin, perfil="Atendimento"))
            session.commit()
    finally:
        session.close()

# ==============================================================================
# 3. CAMADA DE SERVIÇOS & NEGÓCIO
# ==============================================================================
class AuditService:
    @staticmethod
    def registrar(usuario: str, acao: str, detalhes: str = ""):
        session = SessionLocal()
        try:
            log = AuditLogModel(usuario=usuario, acao=acao, detalhes=detalhes)
            session.add(log)
            session.commit()
        except Exception:
            session.rollback()
        finally:
            session.close()

class PDFService:
    @staticmethod
    def gerar_pdf_os(os_id: int) -> bytes:
        session = SessionLocal()
        try:
            os_data = session.query(OrdemServicoModel).options(
                joinedload(OrdemServicoModel.veiculo).joinedload(VeiculoModel.dono)
            ).filter(OrdemServicoModel.id == os_id).first()
            if not os_data:
                return None
            
            buffer = io.BytesIO()
            if not REPORTLAB_DISPONIVEL:
                txt = f"LOJA ENTERPRISE - O.S. #{os_data.id}\nCliente: {os_data.veiculo.dono.nome if os_data.veiculo and os_data.veiculo.dono else 'N/A'}\nPlaca: {os_data.veiculo.placa if os_data.veiculo else 'N/A'}\nTotal: R$ {os_data.valor_total:.2f}"
                return txt.encode('utf-8')

            doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
            story = []
            styles = getSampleStyleSheet()

            style_title = ParagraphStyle('TitleStyle', parent=styles['Heading1'], fontSize=18, textColor=colors.HexColor("#FF3B30"), alignment=1)
            story.append(Paragraph("LOJA AUTOMOTIVE ENTERPRISE", style_title))
            story.append(Paragraph(f"ORDEM DE SERVIÇO #{os_data.id}", styles['Heading3']))
            story.append(Spacer(1, 12))

            nome_cli = os_data.veiculo.dono.nome if os_data.veiculo and os_data.veiculo.dono else "N/A"
            mod_veic = f"{os_data.veiculo.modelo} ({os_data.veiculo.ano})" if os_data.veiculo else "N/A"
            placa_veic = os_data.veiculo.placa if os_data.veiculo else "N/A"

            dados_gerais = [
                ["Data Abertura:", os_data.data_abertura.strftime("%d/%m/%Y %H:%M"), "Status:", os_data.status.upper()],
                ["Cliente:", nome_cli, "Mecânico:", os_data.mecanico],
                ["Veículo:", mod_veic, "Placa:", placa_veic]
            ]
            t_geral = Table(dados_gerais, colWidths=[110, 160, 90, 160])
            t_geral.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#F2F2F7")),
                ('FONTNAME', (0,0), (-1,-1), 'Helvetica-Bold'),
                ('FONTSIZE', (0,0), (-1,-1), 9),
            ]))
            story.append(t_geral)
            story.append(Spacer(1, 15))

            story.append(Paragraph("DIAGNÓSTICO TÉCNICO:", styles['Heading2']))
            story.append(Paragraph(os_data.defeito, styles['BodyText']))
            story.append(Spacer(1, 15))

            dados_fin = [
                ["Discriminação", "Valor (R$)"],
                ["Mão de Obra Técnico", f"R$ {os_data.mao_de_obra:.2f}"],
                ["Peças / Kit (" + str(os_data.kit_utilizado) + ")", f"R$ {os_data.pecas_valor:.2f}"],
                ["TOTAL GERAL", f"R$ {os_data.valor_total:.2f}"]
            ]
            t_fin = Table(dados_fin, colWidths=[380, 140])
            t_fin.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (1,0), colors.HexColor("#1A1A21")),
                ('TEXTCOLOR', (0,0), (1,0), colors.white),
                ('ALIGN', (1,0), (1,-1), 'RIGHT'),
                ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
            ]))
            story.append(t_fin)

            doc.build(story)
            buffer.seek(0)
            return buffer.getvalue()
        finally:
            session.close()

class WhatsAppService:
    @staticmethod
    def gerar_link_whatsapp(telefone: str, os_id: int, cliente: str, modelo: str, placa: str, status: str, valor: float) -> str:
        tel_clean = "".join(filter(str.isdigit, str(telefone)))
        if len(tel_clean) <= 11 and not tel_clean.startswith("55"):
            tel_clean = f"55{tel_clean}"
            
        mensagem = (
            f"Olá *{cliente}*! 🏎️\n\n"
            f"Atualização da sua Ordem de Serviço na *LOJA Performance Enterprise*:\n\n"
            f"📌 *O.S. nº:* #{os_id}\n"
            f"🚘 *Veículo:* {modelo} (Placa: {placa})\n"
            f"🚦 *Status Atual:* {status.upper()}\n"
            f"💰 *Valor Total:* R$ {valor:.2f}\n\n"
            f"Se precisar de suporte, estamos à disposição no box de atendimento!"
        )
        msg_encoded = urllib.parse.quote(mensagem)
        return f"https://wa.me/{tel_clean}?text={msg_encoded}"

# ==============================================================================
# 4. CONTROLE DE SESSÃO & LOGIN
# ==============================================================================
inicializar_banco()

if "autenticado" not in st.session_state:
    st.session_state["autenticado"] = False
    st.session_state["usuario"] = ""
    st.session_state["perfil"] = ""

def tela_login():
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown("<h1 class='header-title' style='text-align: center;'>🏎️ LOJA PERFORMANCE</h1>", unsafe_allow_html=True)
        st.markdown("<p style='text-align: center; color: #94A3B8;'>Cockpit Enterprise Management System</p>", unsafe_allow_html=True)
        st.markdown("<br>", unsafe_allow_html=True)
        
        with st.form("form_login"):
            usuario = st.text_input("Operador / Usuário")
            senha = st.text_input("Chave de Acesso", type="password")
            btn_entrar = st.form_submit_button("AUTENTICAR NO COCKPIT", use_container_width=True)
            
            if btn_entrar:
                senha_hash = hashlib.sha256(senha.encode()).hexdigest()
                session = SessionLocal()
                try:
                    user_db = session.query(UsuarioModel).filter(
                        UsuarioModel.usuario == usuario,
                        UsuarioModel.senha_hash == senha_hash
                    ).first()
                    
                    if user_db:
                        st.session_state["autenticado"] = True
                        st.session_state["usuario"] = user_db.usuario
                        st.session_state["perfil"] = user_db.perfil
                        AuditService.registrar(user_db.usuario, "LOGIN", f"Perfil: {user_db.perfil}")
                        st.success("Autenticado com sucesso!")
                        st.rerun()
                    else:
                        st.error("Credenciais automotivas inválidas.")
                finally:
                    session.close()

if not st.session_state["autenticado"]:
    tela_login()
    st.stop()

# ==============================================================================
# 5. SIDEBAR & NAVEGAÇÃO RBAC
# ==============================================================================
st.sidebar.markdown(f"### 🏁 Piloto: **{st.session_state['usuario']}**")
st.sidebar.markdown(f"Perfil: `{st.session_state['perfil']}`")
st.sidebar.markdown("---")

opcoes_menu = ["🔧 Ordens de Serviço", "📅 Agendamentos & Box", "🚘 Clientes & Garagem", "📦 Almoxarifado & Peças", "🔍 Prontuário do Veículo"]
if st.session_state["perfil"] == "Administrador":
    opcoes_menu.append("📊 Telemetria & Comissões")

menu = st.sidebar.radio("Navegação Cockpit", opcoes_menu)

if st.sidebar.button("Encerrar Sessão", use_container_width=True):
    st.session_state["autenticado"] = False
    st.rerun()

# ==============================================================================
# MÓDULO 1: ORDENS DE SERVIÇO
# ==============================================================================
if menu == "🔧 Ordens de Serviço":
    st.markdown("<h2 class='header-title'>🔧 Ordens de Serviço (Fila de Box)</h2>", unsafe_allow_html=True)
    st.markdown("<br>", unsafe_allow_html=True)
    
    tab_os1, tab_os2 = st.tabs(["➕ Abrir Nova O.S.", "📋 Gerenciar / Editar / Excluir O.S."])
    
    with tab_os1:
        with st.form("form_nova_os"):
            placa_os = st.text_input("Placa do Veículo").upper()
            defeito_os = st.text_area("Diagnóstico / Defeito Relatado")
            mecanico_os = st.text_input("Mecânico Responsável", value="Mecânico 1")
            mao_obra_os = st.number_input("Valor Mão de Obra (R$)", min_value=0.0, step=10.0)
            
            kit_os = st.selectbox("Kit Rápido de Peças", ["Nenhum", "Kit Troca de Óleo Sintético", "Kit Revisão de Freios", "Kit Injeção Eletrônica"])
            status_os = st.selectbox("Status Inicial", ["Aberta", "Em Andamento", "Aguardando Peças", "Concluída"])
            
            btn_salvar_os = st.form_submit_button("GERAR O.S.", use_container_width=True)
            
            if btn_salvar_os:
                if not placa_os or not defeito_os:
                    st.error("Informe a placa e o defeito!")
                else:
                    custo_kit = 0.0
                    if kit_os == "Kit Troca de Óleo Sintético": custo_kit = 220.0
                    elif kit_os == "Kit Revisão de Freios": custo_kit = 380.0
                    elif kit_os == "Kit Injeção Eletrônica": custo_kit = 450.0
                    
                    total = mao_obra_os + custo_kit
                    
                    session = SessionLocal()
                    try:
                        veic = session.query(VeiculoModel).filter(VeiculoModel.placa == placa_os).first()
                        if not veic:
                            st.error(f"Veículo de placa '{placa_os}' não localizado na Garagem!")
                        else:
                            nova_os = OrdemServicoModel(
                                veiculo_id=veic.id,
                                mecanico=mecanico_os,
                                defeito=defeito_os,
                                status=status_os,
                                mao_de_obra=mao_obra_os,
                                pecas_valor=custo_kit,
                                valor_total=total,
                                kit_utilizado=kit_os
                            )
                            session.add(nova_os)
                            session.commit()
                            id_gerado = nova_os.id

                            AuditService.registrar(st.session_state["usuario"], "CRIAR_OS", f"O.S. #{id_gerado} criada para {placa_os}")
                            st.success(f"O.S. #{id_gerado} aberta com sucesso!")
                            st.rerun()
                    finally:
                        session.close()

    with tab_os2:
        st.markdown("<h4 class='sub-title'>Painel de Gestão Completa de O.S.</h4>", unsafe_allow_html=True)
        busca_os = st.text_input("🔍 Filtrar O.S. por Placa, Cliente ou Modelo", "", key="input_busca_os")
        
        session = SessionLocal()
        try:
            query = session.query(OrdemServicoModel).options(
                joinedload(OrdemServicoModel.veiculo).joinedload(VeiculoModel.dono)
            ).outerjoin(VeiculoModel).outerjoin(ClienteModel)

            if busca_os:
                termo = f"%{busca_os.strip()}%"
                query = query.filter(
                    (VeiculoModel.placa.like(termo)) |
                    (ClienteModel.nome.like(termo)) |
                    (VeiculoModel.modelo.like(termo))
                )
            ordens = query.order_by(OrdemServicoModel.id.desc()).all()
            
            if not ordens:
                st.info("Nenhuma Ordem de Serviço encontrada.")
            
            for os_item in ordens:
                nome_cliente = os_item.veiculo.dono.nome if os_item.veiculo and os_item.veiculo.dono else "⚠️ Sem Cliente Vinculado"
                tel_cliente = os_item.veiculo.dono.telefone if os_item.veiculo and os_item.veiculo.dono and os_item.veiculo.dono.telefone else None
                placa_v = os_item.veiculo.placa if os_item.veiculo else "N/A"
                modelo_v = os_item.veiculo.modelo if os_item.veiculo else "N/A"
                
                with st.expander(f"O.S. #{os_item.id} | [{os_item.status.upper()}] | {placa_v} - {modelo_v} ({nome_cliente})"):
                    with st.form(f"form_edit_os_{os_item.id}"):
                        e_mecanico = st.text_input("Mecânico Responsável", value=os_item.mecanico, key=f"emec_{os_item.id}")
                        e_defeito = st.text_area("Diagnóstico / Defeito", value=os_item.defeito, key=f"edef_{os_item.id}")
                        e_mao = st.number_input("Valor Mão de Obra (R$)", value=float(os_item.mao_de_obra), step=10.0, key=f"emao_{os_item.id}")
                        e_kit = st.selectbox("Kit Rápido", ["Nenhum", "Kit Troca de Óleo Sintético", "Kit Revisão de Freios", "Kit Injeção Eletrônica"], index=["Nenhum", "Kit Troca de Óleo Sintético", "Kit Revisão de Freios", "Kit Injeção Eletrônica"].index(os_item.kit_utilizado) if os_item.kit_utilizado in ["Nenhum", "Kit Troca de Óleo Sintético", "Kit Revisão de Freios", "Kit Injeção Eletrônica"] else 0, key=f"ekit_{os_item.id}")
                        e_status = st.selectbox("Status", ["Aberta", "Em Andamento", "Aguardando Peças", "Concluída", "Cancelada"], index=["Aberta", "Em Andamento", "Aguardando Peças", "Concluída", "Cancelada"].index(os_item.status) if os_item.status in ["Aberta", "Em Andamento", "Aguardando Peças", "Concluída", "Cancelada"] else 0, key=f"est_{os_item.id}")
                        
                        btn_salvar_alt = st.form_submit_button("💾 Salvar Alterações na O.S.", use_container_width=True)
                        
                        if btn_salvar_alt:
                            custo_kit_e = 0.0
                            if e_kit == "Kit Troca de Óleo Sintético": custo_kit_e = 220.0
                            elif e_kit == "Kit Revisão de Freios": custo_kit_e = 380.0
                            elif e_kit == "Kit Injeção Eletrônica": custo_kit_e = 450.0
                            
                            os_item.mecanico = e_mecanico
                            os_item.defeito = e_defeito
                            os_item.mao_de_obra = e_mao
                            os_item.kit_utilizado = e_kit
                            os_item.pecas_valor = custo_kit_e
                            os_item.valor_total = e_mao + custo_kit_e
                            
                            if e_status == "Concluída" and os_item.estoque_baixado == 0 and e_kit != "Nenhum":
                                peca_ref = session.query(PecaModel).filter(PecaModel.nome.like(f"%{e_kit}%")).first()
                                if peca_ref and peca_ref.quantidade > 0:
                                    peca_ref.quantidade -= 1
                                os_item.estoque_baixado = 1
                                st.info("Estoque atualizado automaticamente com a baixa do kit!")

                            os_item.status = e_status
                            session.commit()
                            AuditService.registrar(st.session_state["usuario"], "EDITAR_OS", f"O.S. #{os_item.id} atualizada.")
                            st.success("Ordem de serviço atualizada com sucesso!")
                            st.rerun()

                    c1, c2, c3 = st.columns(3)
                    with c1:
                        pdf_data = PDFService.gerar_pdf_os(os_item.id)
                        if pdf_data:
                            st.download_button("📄 Imprimir PDF", pdf_data, file_name=f"OS_{os_item.id}.pdf", mime="application/pdf", key=f"pdf_{os_item.id}")
                    with c2:
                        if tel_cliente:
                            link_wa = WhatsAppService.gerar_link_whatsapp(
                                tel_cliente, os_item.id, nome_cliente,
                                modelo_v, placa_v, os_item.status, os_item.valor_total
                            )
                            st.markdown(f"<a href='{link_wa}' target='_blank' class='btn-whatsapp'>💬 Notificar WhatsApp</a>", unsafe_allow_html=True)
                        else:
                            st.caption("Sem telefone para WhatsApp")
                    with c3:
                        if st.button("🗑️ Excluir O.S.", key=f"del_os_{os_item.id}", use_container_width=True):
                            session.delete(os_item)
                            session.commit()
                            AuditService.registrar(st.session_state["usuario"], "EXCLUIR_OS", f"O.S. #{os_item.id} excluída.")
                            st.warning("Ordem de serviço excluída!")
                            st.rerun()
        finally:
            session.close()

# ==============================================================================
# MÓDULO 2: AGENDAMENTOS E BOX
# ==============================================================================
elif menu == "📅 Agendamentos & Box":
    st.markdown("<h2 class='header-title'>📅 Agenda de Horários & Controle de Box</h2>", unsafe_allow_html=True)
    st.markdown("<br>", unsafe_allow_html=True)
    
    tab_ag1, tab_ag2 = st.tabs(["➕ Novo Agendamento", "📋 Gerenciar / Excluir Agendamentos"])
    
    with tab_ag1:
        with st.form("form_agendar"):
            ag_placa = st.text_input("Placa do Veículo").upper()
            ag_cliente = st.text_input("Nome do Cliente")
            ag_box = st.selectbox("Box de Atendimento", ["Box 01 - Rápido", "Box 02 - Elevador 1", "Box 03 - Elevador 2", "Box 04 - Diagnóstico"])
            ag_mecanico = st.text_input("Mecânico Escalado", value="Mecânico 1")
            ag_data = st.date_input("Data", datetime.date.today())
            ag_hora = st.time_input("Horário", datetime.time(9, 0))
            
            if st.form_submit_button("AGENDAR ENTRADA", use_container_width=True):
                session = SessionLocal()
                try:
                    dt_final = datetime.datetime.combine(ag_data, ag_hora)
                    ag = AgendamentoModel(placa=ag_placa, cliente_nome=ag_cliente, box=ag_box, mecanico=ag_mecanico, data_hora=dt_final)
                    session.add(ag)
                    session.commit()
                    st.success("Agendamento confirmado no Grid!")
                    st.rerun()
                finally:
                    session.close()

    with tab_ag2:
        st.markdown("<h4 class='sub-title'>Grid de Agendamentos Ativos</h4>", unsafe_allow_html=True)
        session = SessionLocal()
        try:
            ags = session.query(AgendamentoModel).order_by(AgendamentoModel.data_hora.asc()).all()
            if ags:
                for a in ags:
                    with st.expander(f"Agendamento #{a.id} | Data: {a.data_hora.strftime('%d/%m/%Y %H:%M')} | Placa: {a.placa} ({a.box})"):
                        with st.form(f"form_edit_ag_{a.id}"):
                            ea_box = st.selectbox("Box", ["Box 01 - Rápido", "Box 02 - Elevador 1", "Box 03 - Elevador 2", "Box 04 - Diagnóstico"], index=["Box 01 - Rápido", "Box 02 - Elevador 1", "Box 03 - Elevador 2", "Box 04 - Diagnóstico"].index(a.box) if a.box in ["Box 01 - Rápido", "Box 02 - Elevador 1", "Box 03 - Elevador 2", "Box 04 - Diagnóstico"] else 0, key=f"ebox_{a.id}")
                            ea_status = st.selectbox("Status", ["Agendado", "Em Andamento", "Concluído", "Cancelado"], index=["Agendado", "Em Andamento", "Concluído", "Cancelado"].index(a.status) if a.status in ["Agendado", "Em Andamento", "Concluído", "Cancelado"] else 0, key=f"east_{a.id}")
                            
                            if st.form_submit_button("💾 Salvar Agendamento"):
                                a.box = ea_box
                                a.status = ea_status
                                session.commit()
                                st.success("Agendamento atualizado!")
                                st.rerun()
                        
                        if st.button("🗑️ Excluir Agendamento", key=f"del_ag_{a.id}"):
                            session.delete(a)
                            session.commit()
                            st.warning("Agendamento excluído!")
                            st.rerun()
            else:
                st.info("Nenhum agendamento pendente.")
        finally:
            session.close()

# ==============================================================================
# MÓDULO 3: CLIENTES & GARAGEM
# ==============================================================================
elif menu == "🚘 Clientes & Garagem":
    st.markdown("<h2 class='header-title'>🚘 Diretório de Clientes & Garagem Central</h2>", unsafe_allow_html=True)
    st.markdown("<br>", unsafe_allow_html=True)
    
    tab_cg1, tab_cg2, tab_cg3 = st.tabs(["➕ Cadastrar Proprietário", "🚘 Vincular Veículo", "📋 Gerenciar / Editar / Excluir Tudo"])
    
    with tab_cg1:
        with st.form("form_cliente"):
            c_nome = st.text_input("Nome Completo")
            c_tel = st.text_input("Telefone / WhatsApp (Ex: 11999998888)")
            c_doc = st.text_input("CPF / CNPJ")
            c_end = st.text_input("Endereço")
            if st.form_submit_button("Salvar Cliente"):
                if c_nome:
                    session = SessionLocal()
                    try:
                        cli = ClienteModel(nome=c_nome, telefone=c_tel, documento=c_doc, endereco=c_end)
                        session.add(cli)
                        session.commit()
                        st.success(f"Cliente registrado com ID: {cli.id}")
                        st.rerun()
                    finally:
                        session.close()
    
    with tab_cg2:
        with st.form("form_veiculo"):
            v_cli_id = st.number_input("ID do Proprietário", step=1)
            v_placa = st.text_input("Placa (Ex: ABC1D23)").upper()
            v_modelo = st.text_input("Modelo / Versão")
            v_ano = st.text_input("Ano Fabricação/Modelo")
            if st.form_submit_button("Salvar na Garagem"):
                session = SessionLocal()
                try:
                    veic = VeiculoModel(cliente_id=int(v_cli_id), placa=v_placa, modelo=v_modelo, ano=v_ano)
                    session.add(veic)
                    session.commit()
                    st.success(f"Veículo {v_modelo} ({v_placa}) registrado!")
                    st.rerun()
                except:
                    st.error("Erro ao cadastrar. Verifique a placa ou se o ID do proprietário existe.")
                finally:
                    session.close()

    with tab_cg3:
        st.markdown("<h4 class='sub-title'>Gestão de Clientes & Veículos Cadastrados</h4>", unsafe_allow_html=True)
        session = SessionLocal()
        try:
            clientes = session.query(ClienteModel).all()
            st.markdown("### 👤 Clientes Cadastrados")
            for cli in clientes:
                with st.expander(f"Cliente ID #{cli.id} - {cli.nome} ({cli.telefone or 'Sem Tel'})"):
                    with st.form(f"form_edit_cli_{cli.id}"):
                        ec_nome = st.text_input("Nome", value=cli.nome, key=f"cnome_{cli.id}")
                        ec_tel = st.text_input("Telefone", value=cli.telefone or "", key=f"ctel_{cli.id}")
                        ec_doc = st.text_input("Documento", value=cli.documento or "", key=f"cdoc_{cli.id}")
                        ec_end = st.text_input("Endereço", value=cli.endereco or "", key=f"cend_{cli.id}")
                        
                        if st.form_submit_button("💾 Atualizar Cliente"):
                            cli.nome = ec_nome
                            cli.telefone = ec_tel
                            cli.documento = ec_doc
                            cli.endereco = ec_end
                            session.commit()
                            st.success("Cliente atualizado!")
                            st.rerun()
                    
                    if st.button(f"🗑️ Excluir Cliente #{cli.id} (e seus veículos)", key=f"del_cli_{cli.id}"):
                        session.delete(cli)
                        session.commit()
                        st.warning("Cliente e veículos associados excluídos!")
                        st.rerun()

            st.markdown("---")
            st.markdown("### 🚘 Veículos na Garagem")
            veiculos = session.query(VeiculoModel).options(joinedload(VeiculoModel.dono)).all()
            for v in veiculos:
                dono_nome = v.dono.nome if v.dono else "Sem Dono"
                with st.expander(f"Placa: {v.placa} | Modelo: {v.modelo} | Dono: {dono_nome}"):
                    with st.form(f"form_edit_veic_{v.id}"):
                        ev_modelo = st.text_input("Modelo", value=v.modelo, key=f"vmod_{v.id}")
                        ev_ano = st.text_input("Ano", value=v.ano or "", key=f"vano_{v.id}")
                        ev_placa = st.text_input("Placa", value=v.placa, key=f"vpla_{v.id}").upper()
                        
                        if st.form_submit_button("💾 Atualizar Veículo"):
                            v.modelo = ev_modelo
                            v.ano = ev_ano
                            v.placa = ev_placa
                            session.commit()
                            st.success("Veículo atualizado!")
                            st.rerun()
                    
                    if st.button(f"🗑️ Excluir Veículo {v.placa}", key=f"del_veic_{v.id}"):
                        session.delete(v)
                        session.commit()
                        st.warning("Veículo excluído!")
                        st.rerun()
        finally:
            session.close()

# ==============================================================================
# MÓDULO 4: ALMOXARIFADO & PEÇAS
# ==============================================================================
elif menu == "📦 Almoxarifado & Peças":
    st.markdown("<h2 class='header-title'>📦 Inventário de Peças & Almoxarifado</h2>", unsafe_allow_html=True)
    st.markdown("<br>", unsafe_allow_html=True)
    
    tab_p1, tab_p2 = st.tabs(["➕ Cadastrar Peça", "📋 Gerenciar / Editar / Excluir Peças"])
    
    with tab_p1:
        with st.form("form_peca"):
            p_nome = st.text_input("Descrição da Peça / Kit")
            p_cod = st.text_input("Código de Barras / Ref")
            p_qtd = st.number_input("Quantidade em Estoque", min_value=0, step=1)
            p_min = st.number_input("Estoque Mínimo", min_value=1, value=3)
            p_custo = st.number_input("Preço Custo (R$)", min_value=0.0, step=5.0)
            p_preco = st.number_input("Preço Venda (R$)", min_value=0.0, step=5.0)
            
            if st.form_submit_button("Registrar Peça"):
                session = SessionLocal()
                try:
                    peca = PecaModel(nome=p_nome, codigo=p_cod, quantidade=int(p_qtd), estoque_minimo=int(p_min), preco_custo=p_custo, preco_venda=p_preco)
                    session.add(peca)
                    session.commit()
                    st.success("Peça adicionada ao Almoxarifado!")
                    st.rerun()
                except:
                    st.error("Código de peça já existente.")
                finally:
                    session.close()

    with tab_p2:
        st.markdown("<h4 class='sub-title'>Gestão de Estoque</h4>", unsafe_allow_html=True)
        session = SessionLocal()
        try:
            pecas = session.query(PecaModel).all()
            if pecas:
                for p in pecas:
                    with st.expander(f"Ref: {p.codigo} | Peça: {p.nome} | Qtd: {p.quantidade} | Venda: R$ {p.preco_venda:.2f}"):
                        with st.form(f"form_edit_peca_{p.id}"):
                            ep_nome = st.text_input("Nome", value=p.nome, key=f"pnome_{p.id}")
                            ep_qtd = st.number_input("Quantidade", value=int(p.quantidade), min_value=0, step=1, key=f"pqtd_{p.id}")
                            ep_min = st.number_input("Mínimo", value=int(p.estoque_minimo), min_value=1, key=f"pmin_{p.id}")
                            ep_custo = st.number_input("Custo R$", value=float(p.preco_custo), step=5.0, key=f"pcusto_{p.id}")
                            ep_preco = st.number_input("Venda R$", value=float(p.preco_venda), step=5.0, key=f"ppreco_{p.id}")
                            
                            if st.form_submit_button("💾 Salvar Alterações na Peça"):
                                p.nome = ep_nome
                                p.quantidade = ep_qtd
                                p.estoque_minimo = ep_min
                                p.preco_custo = ep_custo
                                p.preco_venda = ep_preco
                                session.commit()
                                st.success("Peça atualizada!")
                                st.rerun()
                        
                        if st.button("🗑️ Excluir Peça", key=f"del_peca_{p.id}"):
                            session.delete(p)
                            session.commit()
                            st.warning("Peça excluída do estoque!")
                            st.rerun()
            else:
                st.info("Nenhuma peça cadastrada.")
        finally:
            session.close()

# ==============================================================================
# MÓDULO 5: PRONTUÁRIO COMPLETO DO VEÍCULO
# ==============================================================================
elif menu == "🔍 Prontuário do Veículo":
    st.markdown("<h2 class='header-title'>🔍 Prontuário & Histórico Automotivo</h2>", unsafe_allow_html=True)
    st.markdown("<br>", unsafe_allow_html=True)
    
    placa_busca = st.text_input("Digite a Placa do Veículo para Consultar", "").upper()
    
    if placa_busca:
        session = SessionLocal()
        try:
            veic = session.query(VeiculoModel).options(
                joinedload(VeiculoModel.dono),
                joinedload(VeiculoModel.ordens_servico)
            ).filter(VeiculoModel.placa == placa_busca).first()

            if veic:
                nome_dono = veic.dono.nome if veic.dono else "Sem Proprietário"
                tel_dono = veic.dono.telefone if veic.dono and veic.dono.telefone else "Não informado"
                
                st.markdown(f"### 🏎️ Veículo: **{veic.modelo}** ({veic.ano}) | Placa: `{veic.placa}`")
                st.markdown(f"**Proprietário:** {nome_dono} | **Tel:** {tel_dono}")
                st.markdown("---")
                st.markdown("#### Linha do Tempo de Manutenções:")
                
                if veic.ordens_servico:
                    for os_item in sorted(veic.ordens_servico, key=lambda x: x.id, reverse=True):
                        st.info(
                            f"**O.S. #{os_item.id}** - Data: {os_item.data_abertura.strftime('%d/%m/%Y %H:%M')} | Status: [{os_item.status}]\n\n"
                            f"**Mecânico:** {os_item.mecanico} | **Diagnóstico:** {os_item.defeito}\n\n"
                            f"**Mão de Obra:** R$ {os_item.mao_de_obra:.2f} | **Peças:** R$ {os_item.pecas_valor:.2f} | **TOTAL:** R$ {os_item.valor_total:.2f}"
                        )
                else:
                    st.warning("Nenhuma O.S. cadastrada para este veículo.")
            else:
                st.error("Veículo não localizado na base de dados.")
        finally:
            session.close()

# ==============================================================================
# MÓDULO 6: TELEMETRIA, DASHBOARDS INTERATIVOS & EXPORTAÇÕES (ADMIN EXCLUSIVE)
# ==============================================================================
elif menu == "📊 Telemetria & Comissões":
    if st.session_state["perfil"] != "Administrador":
        st.error("Acesso exclusivo para administradores.")
    else:
        st.markdown("<h2 class='header-title'>📊 Telemetria Executiva, BI & Backups</h2>", unsafe_allow_html=True)
        st.markdown("<br>", unsafe_allow_html=True)
        
        session = SessionLocal()
        try:
            fat_total = session.query(OrdemServicoModel.valor_total).filter(OrdemServicoModel.status == 'Concluída').all()
            total_fat = sum([f[0] for f in fat_total]) if fat_total else 0.0
            
            c_m1, c_m2, c_m3 = st.columns(3)
            c_m1.metric("Faturamento Concluído", f"R$ {total_fat:.2f}")
            c_m2.metric("O.S. Registradas", session.query(OrdemServicoModel).count())
            c_m3.metric("Frota na Garagem", session.query(VeiculoModel).count())
            
            st.markdown("---")
            
            if PLOTLY_DISPONIVEL:
                st.markdown("<h4 class='sub-title'>Cockpit de Inteligência Financeira (BI)</h4>", unsafe_allow_html=True)
                col_g1, col_g2 = st.columns(2)
                
                ordens_all = session.query(OrdemServicoModel).all()
                if ordens_all:
                    df_status = pd.DataFrame([{"Status": o.status} for o in ordens_all])
                    df_status_count = df_status['Status'].value_counts().reset_index()
                    df_status_count.columns = ['Status', 'Quantidade']
                    
                    fig_status = px.pie(
                        df_status_count, values='Quantidade', names='Status',
                        title="Distribuição de O.S. por Status",
                        color_discrete_sequence=['#FF3B30', '#FF9500', '#34C759', '#8E8E93'],
                        hole=0.4
                    )
                    fig_status.update_layout(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', font_color='#FAFAFA')
                    col_g1.plotly_chart(fig_status, use_container_width=True)
                    
                    total_mo = sum([o.mao_de_obra for o in ordens_all if o.status == 'Concluída'])
                    total_pec = sum([o.pecas_valor for o in ordens_all if o.status == 'Concluída'])
                    
                    df_comp = pd.DataFrame({
                        "Categoria": ["Mão de Obra", "Peças / Kits"],
                        "Valor (R$)": [total_mo, total_pec]
                    })
                    fig_comp = px.bar(
                        df_comp, x="Categoria", y="Valor (R$)", text_auto='.2f',
                        title="Origem do Faturamento (Concluídas)",
                        color="Categoria", color_discrete_sequence=['#FF3B30', '#34C759']
                    )
                    fig_comp.update_layout(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', font_color='#FAFAFA')
                    col_g2.plotly_chart(fig_comp, use_container_width=True)
            
            st.markdown("---")
            st.markdown("<h4 class='sub-title'>Comissões por Mecânico (20% Mão de Obra)</h4>", unsafe_allow_html=True)
            
            ordens_conc = session.query(OrdemServicoModel).filter(OrdemServicoModel.status == 'Concluída').all()
            if ordens_conc:
                comissoes = {}
                for o in ordens_conc:
                    mec = o.mecanico or "Não Atribuído"
                    comissao = o.mao_de_obra * 0.20
                    comissoes[mec] = comissoes.get(mec, 0.0) + comissao
                
                df_com = pd.DataFrame([{"Mecânico": k, "Comissão Devida (20%)": f"R$ {v:.2f}"} for k, v in comissoes.items()])
                st.dataframe(df_com, use_container_width=True)

            st.markdown("---")
            st.markdown("<h4 class='sub-title'>Central de Exportação & Security Backup</h4>", unsafe_allow_html=True)
            
            e_col1, e_col2 = st.columns(2)
            with e_col1:
                ordens_all = session.query(OrdemServicoModel).options(
                    joinedload(OrdemServicoModel.veiculo).joinedload(VeiculoModel.dono)
                ).all()
                if ordens_all:
                    df_export_os = pd.DataFrame([{
                        "ID": o.id, "Data": o.data_abertura.strftime("%Y-%m-%d %H:%M"),
                        "Placa": o.veiculo.placa if o.veiculo else "N/A",
                        "Modelo": o.veiculo.modelo if o.veiculo else "N/A",
                        "Cliente": o.veiculo.dono.nome if o.veiculo and o.veiculo.dono else "N/A",
                        "Mecânico": o.mecanico, "Mão de Obra": o.mao_de_obra, "Peças": o.pecas_valor,
                        "Total": o.valor_total, "Status": o.status
                    } for o in ordens_all])
                    
                    csv_os = df_export_os.to_csv(index=False).encode('utf-8')
                    st.download_button("📊 Exportar Relatório de O.S. (CSV)", csv_os, "relatorio_ordens_servico.csv", "text/csv")
            
            with e_col2:
                try:
                    with open("oficina_enterprise.db", "rb") as db_file:
                        db_bytes = db_file.read()
                    st.download_button("💾 Baixar Backup do Banco (.DB)", db_bytes, "oficina_enterprise.db", "application/x-sqlite3")
                except FileNotFoundError:
                    st.caption("Banco de dados local não pronto para backup.")
        finally:
            session.close()
