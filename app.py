import streamlit as st
import pandas as pd
import pdfplumber
import re
from io import BytesIO

# --- Funções de Extração (as mesmas que desenvolvemos antes) ---

def limpar_valor(valor_texto):
    if isinstance(valor_texto, str):
        try:
            valor_limpo = re.sub(r'[^\d,]', '', valor_texto).replace(',', '.')
            return float(valor_limpo)
        except (ValueError, AttributeError):
            return 0.0
    return 0.0

def identificar_tipo_extrato(texto):
    if "Investimentos Fundos" in texto:
        return "INVESTIMENTOS"
    if "Extrato de Conta Corrente" in texto:
        return "CONTA_CORRENTE"
    return "DESCONHECIDO"

def extrair_dados_cabecalho(texto):
    dados = {"agencia": None, "conta": None, "periodo": None}
    match_agencia = re.search(r"Agência\s*([\d-]+)", texto)
    if match_agencia:
        dados["agencia"] = match_agencia.group(1).strip()
    match_conta = re.search(r"(?:Conta corrente|Conta)\s*([\d\.-]+)", texto)
    if match_conta:
        dados["conta"] = match_conta.group(1).strip()
    match_periodo = re.search(r"Mês/ano referência\s*([A-Z]+/\d{4})", texto)
    if match_periodo:
        dados["periodo"] = match_periodo.group(1).strip()
    return dados

def extrair_dados_investimentos(texto):
    if "NÃO HOUVE MOVIMENTO NO PERÍODO SOLICITADO." in texto:
        return {"situacao": "Sem Movimento", "saldo_anterior": 0.0, "aplicacoes": 0.0, "resgates": 0.0, "rendimento_liquido": 0.0, "saldo_atual": 0.0}
    
    saldo_anterior = re.search(r"SALDO ANTERIOR\s*([\d\.,]+)", texto)
    aplicacoes = re.search(r"APLICAÇÕES \(\+\)\s*([\d\.,]+)", texto)
    resgates = re.search(r"RESGATES \(-\)\s*([\d\.,]+)", texto)
    rendimento = re.search(r"RENDIMENTO LÍQUIDO\s*([\d\.,]+)", texto)
    saldo_atual = re.search(r"SALDO ATUAL =\s*([\d\.,]+)", texto)

    return {
        "situacao": "Com Movimento",
        "saldo_anterior": limpar_valor(saldo_anterior.group(1) if saldo_anterior else '0,00'),
        "aplicacoes": limpar_valor(aplicacoes.group(1) if aplicacoes else '0,00'),
        "resgates": limpar_valor(resgates.group(1) if resgates else '0,00'),
        "rendimento_liquido": limpar_valor(rendimento.group(1) if rendimento else '0,00'),
        "saldo_atual": limpar_valor(saldo_atual.group(1) if saldo_atual else '0,00')
    }

# --- Função de Processamento Adaptada para Streamlit ---

def processar_extrato_pdf(ficheiro_pdf):
    try:
        with pdfplumber.open(ficheiro_pdf) as pdf:
            texto_completo = "".join([pagina.extract_text(x_tolerance=2) or "" for pagina in pdf.pages])
            tipo_extrato = identificar_tipo_extrato(texto_completo)
            
            if tipo_extrato != "INVESTIMENTOS":
                return None

            dados_comuns = extrair_dados_cabecalho(texto_completo)
            dados_comuns["ficheiro"] = ficheiro_pdf.name
            dados_comuns["tipo_extrato"] = tipo_extrato
            dados_especificos = extrair_dados_investimentos(texto_completo)
            
            return {**dados_comuns, **dados_especificos}
    except Exception as e:
        st.error(f"Erro ao processar o ficheiro {ficheiro_pdf.name}: {e}")
        return None

# --- Interface da Aplicação Streamlit ---

st.set_page_config(layout="wide")
st.title(" ferramenta de Pré-Conciliação Bancária")

st.info("Carregue os extratos de investimentos (PDF) e a planilha de movimentação (CSV) para preparar os dados para a conciliação.")

# Colunas para organizar a interface
col1, col2 = st.columns(2)

with col1:
    st.header("1. Carregar Extratos (PDF)")
    extratos_pdf = st.file_uploader(
        "Selecione os extratos de investimentos",
        type="pdf",
        accept_multiple_files=True
    )

with col2:
    st.header("2. Carregar Movimentação (CSV)")
    movimentacao_csv = st.file_uploader(
        "Selecione a sua planilha de movimentação",
        type="csv"
    )

if st.button("Processar e Preparar Dados", type="primary"):
    # Processar Extratos PDF
    if not extratos_pdf:
        st.warning("Por favor, carregue pelo menos um extrato PDF.")
    else:
        dados_extratos = []
        with st.spinner("A extrair dados dos extratos..."):
            for extrato in extratos_pdf:
                dados = processar_extrato_pdf(extrato)
                if dados:
                    dados_extratos.append(dados)
        
        if not dados_extratos:
            st.error("Nenhum extrato de investimento válido foi encontrado nos PDFs carregados.")
        else:
            df_extratos = pd.DataFrame(dados_extratos)
            st.session_state['df_extratos'] = df_extratos

    # Processar Planilha CSV
    if not movimentacao_csv:
        st.warning("Por favor, carregue o ficheiro CSV de movimentação.")
    else:
        with st.spinner("A carregar planilha de movimentação..."):
            # O ficheiro CSV usa ';' como separador
            df_movimentacao = pd.read_csv(movimentacao_csv, sep=';', decimal=',')
            st.session_state['df_movimentacao'] = df_movimentacao

# --- Secção de Resultados ---

if 'df_extratos' in st.session_state and 'df_movimentacao' in st.session_state:
    st.success("Dados processados e prontos para a conciliação!")
    st.header("Dados Reservados para Conciliação")

    # Mostrar dados dos extratos
    st.subheader("Resultado Extraído dos Extratos PDF")
    st.dataframe(st.session_state.df_extratos)
    st.download_button(
        label="Descarregar CSV dos Extratos",
        data=st.session_state.df_extratos.to_csv(sep=';', decimal=',', index=False).encode('utf-8'),
        file_name='resultado_extratos.csv',
        mime='text/csv',
    )

    st.divider()

    # Mostrar dados da movimentação
    st.subheader("Dados da Planilha de Movimentação")
    st.dataframe(st.session_state.df_movimentacao)
    st.download_button(
        label="Descarregar CSV da Movimentação",
        data=st.session_state.df_movimentacao.to_csv(sep=';', decimal=',', index=False).encode('utf-8'),
        file_name='movimentacao_original.csv',
        mime='text/csv',
    )
