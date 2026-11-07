# 🏎️ LOJA Performance Enterprise (Streamlit + GitHub)

Sistema de gestão de oficina automotiva e Ordens de Serviço desenvolvido em Python com **Streamlit**, **SQLAlchemy** e **ReportLab**.

## 🚀 Funcionalidades
- **Grid de Box & Agendamentos:** Controle de entrada de veículos por box e horário.
- **Ordens de Serviço:** Abertura, cálculo de mão de obra e kits rápidos, mudança de status em tempo real.
- **Garagem & Clientes:** Diretório completo de proprietários e frota vinculada.
- **Almoxarifado & Alertas:** Controle de estoque com alertas para reposição de peças críticas.
- **Prontuário Automotivo:** Consulta da linha do tempo de manutenções por placa.
- **Relatórios em PDF:** Emissão de comprovantes de O.S. formatados para impressão.
- **Comissões & Telemetria:** Painel executivo com cálculo automático de comissão dos mecânicos (20%) e logs de segurança.

---

## 🛠️ Como rodar localmente

1. Clone o repositório:
```bash
git clone https://github.com/seu-usuario/loja-performance.git
cd loja-performance
```

2. Instale as dependências:
```bash
pip install -r requirements.txt
```

3. Execute a aplicação Streamlit:
```bash
streamlit run app.py
```

---

## 🌐 Como fazer o Deploy no Streamlit Community Cloud (Gratuito)

1. Crie um repositório no seu **GitHub** com os arquivos deste projeto (`app.py`, `requirements.txt`, `README.md`).
2. Acesse [share.streamlit.io](https://share.streamlit.io/) e faça login com seu GitHub.
3. Clique em **New App**.
4. Selecione o repositório criado, a branch `main` e defina o Main file path como `app.py`.
5. Clique em **Deploy!** Seu sistema estará online em um link público seguro.

---
**Credenciais de Acesso Padrão:**
- **Usuário:** `admin` | **Senha:** `admin123`
