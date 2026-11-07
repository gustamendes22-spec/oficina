import streamlit as st
import pandas as pd
import datetime
import hashlib
import sqlite3
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, ForeignKey, Text
from sqlalchemy.orm import declarative_base, sessionmaker, relationship, scoped_session
import io
import zipfile

# --- GERADOR DE PDF (ReportLab) ---
try:
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors
    REPORTLAB_DISPONIVEL = True
except ImportError:
    REPORTLAB_DISPONIVEL = False

# ==============================================================================
# 1. CONFIGURAÇÃO DA PÁGINA STREAMLIT & DESIGN AUTOMOTIVO COCKPIT DARK
# ==============================================================================
st.set_page_config(
    page_title="LOJA Performance Enterprise",
    page_icon="🏎️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Injeção de CSS Customizado para Tema Cockpit Dark de Alto Desempenho
st.markdown("""
    <style>
    /* Fundo Principal e Cores de Texto */
    .stApp {
        background-color: #0F0F12;
        color: #FAFAFA;
    }
    
    /* Sidebar Grafite Metálico */
    [data-testid="stSidebar"] {
        background-color: #1A1A21;
        border-right: 1px solid #2A2A35;
    }
    
    /* Botões em Vermelho Neon Racing */
    div.stButton > button {
        background-color: #FF3B30 !important;
        color: white !important;
        font-weight: bold !important;
        border-radius: 6px !important;
        border: none !important;
        transition: all 0.3s ease;
    }
    div.stButton > button:hover {
        background-color: #D32F2F !important;
        box-shadow: 0 0 10px rgba(255, 59, 48, 0.5);
    }
    
    /* Entradas de Texto e Seletores */
    div[data-baseweb="input"] > div, div[data-baseweb="select"] > div {
        background-color: #0F0F12 !important;
        color: #FAFAFA !important;
        border-color: #2A2A35 !important;
    }
    
    /* Métrica / Cards de Telemetria */
    [data-testid="stMetricValue"] {
        color: #34C759 !important;
        font-family: 'Impact', sans-serif;
    }
    
    /* Custom Headers */
    .header-title {
        color: #FF3B30;
        font-family: 'Impact', sans-serif;
        font-size: 2.2rem;
        letter-spacing: 1px;
    }
    .sub-title {
        color: #FF9500;
        font-weight: bold;
    }
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
            session.commit()
    finally:
        session.close()

# ==============================================================================
# 3. CAMADA DE SERVIÇOS
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
            os_data = session.query(OrdemServicoModel).filter(OrdemServicoModel.id == os_id).first()
            if not os_data:
                return None
            
            buffer = io.BytesIO()
            if not REPORTLAB_DISPONIVEL:
                txt = f"LOJA ENTERPRISE - O.S. #{os_data.id}\nCliente: {os_data.veiculo.dono.nome}\nPlaca: {os_data.veiculo.placa}\nTotal: R$ {os_data.valor_total:.2f}"
                return txt.encode('utf-8')

            doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
            story = []
            styles = getSampleStyleSheet()

            style_title = ParagraphStyle('TitleStyle', parent=styles['Heading1'], fontSize=18, textColor=colors.HexColor("#FF3B30"), alignment=1)
            story.append(Paragraph("LOJA AUTOMOTIVE ENTERPRISE", style_title))
            story.append(Paragraph(f"ORDEM DE SERVIÇO #{os_data.id}", styles['Heading3']))
            story.append(Spacer(1, 12))

            dados_gerais = [
                ["Data Abertura:", os_data.data_abertura.strftime("%d/%m/%Y %H:%M"), "Status:", os_data.status.upper()],
                ["Cliente:", os_data.veiculo.dono.nome, "Mecânico:", os_data.mecanico],
                ["Veículo:", f"{os_data.veiculo.modelo} ({os_data.veiculo.ano})", "Placa:", os_data.veiculo.placa]
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
                ["Peças / Componentes", f"R$ {os_data.pecas_valor:.2f}"],
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

# ==============================================================================
# 4. INICIALIZAÇÃO DE SESSÃO & LOGIN
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
        st.markdown("<p style='text-align: center; color: gray;'>Gestão Automotiva Cockpit Enterprise</p>", unsafe_allow_html=True)
        
        with st.form("form_login"):
            usuario = st.text_input("Usuário do Operador")
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
                        st.success("Login efetuado com sucesso!")
                        st.rerun()
                    else:
                        st.error("Credenciais automotivas inválidas.")
                finally:
                    session.close()

if not st.session_state["autenticado"]:
    tela_login()
    st.stop()

# ==============================================================================
# 5. ESTRUTURA PRINCIPAL (SIDEBAR & NAVEGAÇÃO)
# ==============================================================================
st.sidebar.markdown(f"### 🏁 Piloto: **{st.session_state['usuario']}**")
st.sidebar.markdown(f"Perfil: `{st.session_state['perfil']}`")
st.sidebar.markdown("---")

menu = st.sidebar.radio(
    "Navegação Cockpit",
    [
        "🔧 Ordens de Serviço",
        "📅 Agendamentos & Box",
        "🚘 Clientes & Garagem",
        "📦 Almoxarifado & Peças",
        "🔍 Prontuário do Veículo",
        "📊 Telemetria & Comissões"
    ]
)

if st.sidebar.button("Encerrar Sessão", use_container_width=True):
    st.session_state["autenticado"] = False
    st.rerun()

# ==============================================================================
# MÓDULO 1: ORDENS DE SERVIÇO
# ==============================================================================
if menu == "🔧 Ordens de Serviço":
    st.markdown("<h2 class='header-title'>🔧 Ordens de Serviço (Fila de Box)</h2>", unsafe_allow_html=True)
    
    col_form, col_list = st.columns([1, 2])
    
    with col_form:
        st.markdown("<h4 class='sub-title'>Abrir Nova O.S.</h4>", unsafe_allow_html=True)
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
                            st.error(f"Veículo com placa '{placa_os}' não encontrado na Garagem!")
                        else:
                            nova_os = OrdemServicoModel(
                                veiculo_id=veic.id,
                                mecanico=mecanico_os,
                                defeito=defeito_os,
                                status=status_os,
                                mao_de_obra=mao_obra_os,
                                pecas_valor=custo_kit,
                                valor_total=total
                            )
                            session.add(nova_os)
                            session.commit()
                            AuditService.registrar(st.session_state["usuario"], "CRIAR_OS", f"O.S. #{nova_os.id} criada para {placa_os}")
                            st.success(f"O.S. #{nova_os.id} criada com sucesso!")
                            st.rerun()
                    finally:
                        session.close()

    with col_list:
        st.markdown("<h4 class='sub-title'>Painel Reativo de O.S.</h4>", unsafe_allow_html=True)
        busca_os = st.text_input("🔍 Filtrar por Placa, Cliente ou Modelo", "")
        
        session = SessionLocal()
        try:
            query = session.query(OrdemServicoModel).join(VeiculoModel).join(ClienteModel)
            if busca_os:
                query = query.filter(
                    (VeiculoModel.placa.like(f"%{busca_os}%")) |
                    (ClienteModel.nome.like(f"%{busca_os}%")) |
                    (VeiculoModel.modelo.like(f"%{busca_os}%"))
                )
            ordens = query.order_by(OrdemServicoModel.id.desc()).all()
            
            for os_item in ordens:
                with st.expander(f"O.S. #{os_item.id} | [{os_item.status.upper()}] | {os_item.veiculo.placa} - {os_item.veiculo.modelo}"):
                    st.write(f"**Cliente:** {os_item.veiculo.dono.nome} | **Mecânico:** {os_item.mecanico}")
                    st.write(f"**Diagnóstico:** {os_item.defeito}")
                    st.write(f"**Mão de Obra:** R$ {os_item.mao_de_obra:.2f} | **Peças:** R$ {os_item.pecas_valor:.2f} | **TOTAL:** R$ {os_item.valor_total:.2f}")
                    
                    c1, c2, c3 = st.columns(3)
                    with c1:
                        novo_st = st.selectbox("Atualizar Status", ["Aberta", "Em Andamento", "Concluída", "Cancelada"], key=f"st_{os_item.id}", index=["Aberta", "Em Andamento", "Concluída", "Cancelada"].index(os_item.status) if os_item.status in ["Aberta", "Em Andamento", "Concluída", "Cancelada"] else 0)
                        if st.button("Salvar Status", key=f"btn_st_{os_item.id}"):
                            os_item.status = novo_st
                            session.commit()
                            AuditService.registrar(st.session_state["usuario"], "ALTERAR_STATUS", f"O.S. #{os_item.id} -> {novo_st}")
                            st.success("Status atualizado!")
                            st.rerun()
                    with c2:
                        pdf_data = PDFService.gerar_pdf_os(os_item.id)
                        st.download_button("📄 Baixar PDF", pdf_data, file_name=f"OS_{os_item.id}.pdf", mime="application/pdf", key=f"pdf_{os_item.id}")
                    with c3:
                        if st.session_state["perfil"] == "Administrador":
                            if st.button("🗑️ Excluir O.S.", key=f"del_{os_item.id}"):
                                session.delete(os_item)
                                session.commit()
                                AuditService.registrar(st.session_state["usuario"], "EXCLUIR_OS", f"O.S. #{os_item.id}")
                                st.success("O.S. removida!")
                                st.rerun()
        finally:
            session.close()

# ==============================================================================
# MÓDULO 2: AGENDAMENTOS E BOX
# ==============================================================================
elif menu == "📅 Agendamentos & Box":
    st.markdown("<h2 class='header-title'>📅 Agenda de Horários & Controle de Box</h2>", unsafe_allow_html=True)
    
    col_a1, col_a2 = st.columns([1, 2])
    
    with col_a1:
        st.markdown("<h4 class='sub-title'>Novo Agendamento</h4>", unsafe_allow_html=True)
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
                    st.success("Agendamento cadastrado no Grid de Box!")
                    st.rerun()
                finally:
                    session.close()

    with col_a2:
        st.markdown("<h4 class='sub-title'>Grid de Box Agendados</h4>", unsafe_allow_html=True)
        session = SessionLocal()
        try:
            ags = session.query(AgendamentoModel).order_by(AgendamentoModel.data_hora.asc()).all()
            if ags:
                df_ag = pd.DataFrame([{
                    "ID": a.id, "Data/Hora": a.data_hora.strftime("%d/%m/%Y %H:%M"),
                    "Placa": a.placa, "Cliente": a.cliente_nome, "Box": a.box,
                    "Mecânico": a.mecanico, "Status": a.status
                } for a in ags])
                st.dataframe(df_ag, use_container_width=True)
            else:
                st.info("Nenhum agendamento pendente no Grid.")
        finally:
            session.close()

# ==============================================================================
# MÓDULO 3: CLIENTES & GARAGEM
# ==============================================================================
elif menu == "🚘 Clientes & Garagem":
    st.markdown("<h2 class='header-title'>🚘 Diretório de Clientes & Garagem Central</h2>", unsafe_allow_html=True)
    
    c_cli, c_veic = st.columns(2)
    
    with c_cli:
        st.markdown("<h4 class='sub-title'>1. Cadastrar Proprietário</h4>", unsafe_allow_html=True)
        with st.form("form_cliente"):
            c_nome = st.text_input("Nome Completo")
            c_tel = st.text_input("Telefone / WhatsApp")
            c_doc = st.text_input("CPF / CNPJ")
            c_end = st.text_input("Endereço")
            if st.form_submit_button("Salvar Cliente"):
                if c_nome:
                    session = SessionLocal()
                    try:
                        cli = ClienteModel(nome=c_nome, telefone=c_tel, documento=c_doc, endereco=c_end)
                        session.add(cli)
                        session.commit()
                        st.success(f"Cliente cadastrado com ID: {cli.id}")
                        st.rerun()
                    finally:
                        session.close()
    
    with c_veic:
        st.markdown("<h4 class='sub-title'>2. Vincular Veículo na Garagem</h4>", unsafe_allow_html=True)
        with st.form("form_veiculo"):
            v_cli_id = st.number_input("ID do Proprietário (Dono)", step=1)
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
                    st.error("Erro ao cadastrar. Verifique a placa ou o ID do cliente.")
                finally:
                    session.close()

    st.markdown("---")
    st.markdown("<h4 class='sub-title'>Frota de Veículos Cadastrada</h4>", unsafe_allow_html=True)
    session = SessionLocal()
    try:
        veiculos = session.query(VeiculoModel).all()
        if veiculos:
            df_v = pd.DataFrame([{
                "ID Veículo": v.id, "Placa": v.placa, "Modelo": v.modelo, "Ano": v.ano,
                "Proprietário": v.dono.nome, "Telefone": v.dono.telefone
            } for v in veiculos])
            st.dataframe(df_v, use_container_width=True)
    finally:
        session.close()

# ==============================================================================
# MÓDULO 4: ALMOXARIFADO & PEÇAS
# ==============================================================================
elif menu == "📦 Almoxarifado & Peças":
    st.markdown("<h2 class='header-title'>📦 Inventário de Peças & Almoxarifado</h2>", unsafe_allow_html=True)
    
    col_p1, col_p2 = st.columns([1, 2])
    
    with col_p1:
        st.markdown("<h4 class='sub-title'>Entrada de Autopeças</h4>", unsafe_allow_html=True)
        with st.form("form_peca"):
            p_nome = st.text_input("Descrição da Peça")
            p_cod = st.text_input("Código de Barras / Ref")
            p_qtd = st.number_input("Quantidade em Estoque", min_value=0, step=1)
            p_min = st.number_input("Estoque Mínimo de Segurança", min_value=1, value=3)
            p_preco = st.number_input("Preço de Venda (R$)", min_value=0.0, step=5.0)
            
            if st.form_submit_button("Registrar Peça"):
                session = SessionLocal()
                try:
                    peca = PecaModel(nome=p_nome, codigo=p_cod, quantidade=int(p_qtd), estoque_minimo=int(p_min), preco_venda=p_preco)
                    session.add(peca)
                    session.commit()
                    st.success("Peça cadastrada no Almoxarifado!")
                    st.rerun()
                except:
                    st.error("Código de peça já existente.")
                finally:
                    session.close()

    with col_p2:
        st.markdown("<h4 class='sub-title'>Estoque & Alerta de Reposição</h4>", unsafe_allow_html=True)
        session = SessionLocal()
        try:
            pecas = session.query(PecaModel).all()
            if pecas:
                df_p = pd.DataFrame([{
                    "Código": p.codigo, "Peça": p.nome, "Qtd Estoque": p.quantidade,
                    "Mínimo": p.estoque_minimo, "Preço Unitário": f"R$ {p.preco_venda:.2f}",
                    "Status Alerta": "⚠️ REPOR ESTOQUE" if p.quantidade <= p.estoque_minimo else "✅ OK"
                } for p in pecas])
                st.dataframe(df_p, use_container_width=True)
        finally:
            session.close()

# ==============================================================================
# MÓDULO 5: PRONTUÁRIO COMPLETO DO VEÍCULO
# ==============================================================================
elif menu == "🔍 Prontuário do Veículo":
    st.markdown("<h2 class='header-title'>🔍 Prontuário & Histórico Automotivo</h2>", unsafe_allow_html=True)
    
    placa_busca = st.text_input("Digite a Placa do Veículo para Consultar o Histórico", "").upper()
    
    if placa_busca:
        session = SessionLocal()
        try:
            veic = session.query(VeiculoModel).filter(VeiculoModel.placa == placa_busca).first()
            if veic:
                st.markdown(f"### 🏎️ Veículo: **{veic.modelo}** ({veic.ano}) | Placa: `{veic.placa}`")
                st.markdown(f"**Proprietário:** {veic.dono.nome} | **Tel:** {veic.dono.telefone}")
                st.markdown("---")
                st.markdown("#### Linha do Tempo de Serviços Realizados:")
                
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
# MÓDULO 6: TELEMETRIA, COMISSÕES & LOGS (ADMIN)
# ==============================================================================
elif menu == "📊 Telemetria & Comissões":
    if st.session_state["perfil"] != "Administrador":
        st.error("Acesso exclusivo para administradores.")
    else:
        st.markdown("<h2 class='header-title'>📊 Painel Executivo de Telemetria & Comissões</h2>", unsafe_allow_html=True)
        
        session = SessionLocal()
        try:
            fat_total = session.query(OrdemServicoModel.valor_total).filter(OrdemServicoModel.status == 'Concluída').all()
            total_fat = sum([f[0] for f in fat_total]) if fat_total else 0.0
            
            c_m1, c_m2, c_m3 = st.columns(3)
            c_m1.metric("Faturamento Bruto (Concluídas)", f"R$ {total_fat:.2f}")
            c_m2.metric("Total O.S. Registradas", session.query(OrdemServicoModel).count())
            c_m3.metric("Veículos na Garagem", session.query(VeiculoModel).count())
            
            st.markdown("---")
            st.markdown("<h4 class='sub-title'>Cálculo de Comissão por Mecânico (20% Mão de Obra)</h4>", unsafe_allow_html=True)
            
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
            st.markdown("<h4 class='sub-title'>Logs de Auditoria de Segurança</h4>", unsafe_allow_html=True)
            logs = session.query(AuditLogModel).order_by(AuditLogModel.id.desc()).limit(20).all()
            if logs:
                df_l = pd.DataFrame([{
                    "Data/Hora": l.timestamp.strftime("%d/%m/%Y %H:%M"),
                    "Usuário": l.usuario, "Ação": l.acao, "Detalhes": l.detalhes
                } for l in logs])
                st.dataframe(df_l, use_container_width=True)
        finally:
            session.close()
