import streamlit as st
import pandas as pd
import pdfplumber
import re
from io import BytesIO

st.set_page_config(layout="wide")
st.title(" ferramenta de Conciliação Bancária")

# --- FUNÇÕES AUXILIARES E DE EXTRAÇÃO ---

def criar_chave_conta(numero_conta):
    try:
        s = str(numero_conta)
        numeros = re.sub(r'\D', '', s)
        chave = numeros[-5:]
        return chave.zfill(5)
    except:
        return None

def limpar_valor(valor_texto):
    if isinstance(valor_texto, str):
        try:
            valor_limpo = re.sub(r'[^\d,]', '', valor_texto).replace(',', '.')
            return float(valor_limpo)
        except (ValueError, AttributeError):
            return 0.0
    return 0.0

def identificar_tipo_extrato(texto):
    if "Investimentos Fundos" in texto: return "INVESTIMENTOS"
    return "DESCONHECIDO"

def extrair_dados_cabecalho(texto):
    dados = {"agencia": None, "conta": None, "periodo": None}
    match_agencia = re.search(r"Agência\s*([\d-]+)", texto)
    if match_agencia: dados["agencia"] = match_agencia.group(1).strip()
    match_conta = re.search(r"(?:Conta corrente|Conta)\s*([\d\.-]+)", texto)
    if match_conta: dados["conta"] = match_conta.group(1).strip()
    match_periodo = re.search(r"Mês/ano referência\s*([A-Z]+/\d{4})", texto)
    if match_periodo: dados["periodo"] = match_periodo.group(1).strip()
    return dados

def extrair_dados_investimentos(pdf_page):
    transacoes = []
    tabelas = pdf_page.extract_tables()
    for tabela in tabelas:
        # Lógica para extratos detalhados
        for linha in tabela:
            if len(linha) > 2 and linha[1] and isinstance(linha[1], str) and linha[1].strip() in ("APLICAÇÃO", "RESGATE"):
                try:
                    transacoes.append({"data": linha[0], "historico": linha[1].strip(), "valor": limpar_valor(linha[2])})
                except (IndexError, TypeError): continue
        # Lógica para extratos de resumo
        if not transacoes:
            saldo_anterior, saldo_atual = None, None
            for linha in tabela:
                if len(linha) > 2 and isinstance(linha[1], str):
                    if linha[1].strip() == "SALDO ANTERIOR": saldo_anterior = {"data": linha[0], "valor": limpar_valor(linha[2])}
                    elif linha[1].strip() == "SALDO ATUAL": saldo_atual = {"data": linha[0], "valor": limpar_valor(linha[2])}
            if saldo_anterior and saldo_atual:
                rendimento = round(saldo_atual["valor"] - saldo_anterior["valor"], 2)
                if rendimento > 0:
                    transacoes.append({"data": saldo_atual["data"], "historico": "RENDIMENTO", "valor": rendimento})
    return transacoes

def processar_extratos_pdf(lista_ficheiros_pdf):
    lista_transacoes_finais = []
    for ficheiro_pdf in lista_ficheiros_pdf:
        try:
            with pdfplumber.open(ficheiro_pdf) as pdf:
                for page in pdf.pages:
                    texto_completo = page.extract_text(x_tolerance=2) or ""
                    if identificar_tipo_extrato(texto_completo) == "INVESTIMENTOS":
                        dados_cabecalho = extrair_dados_cabecalho(texto_completo)
                        transacoes = extrair_dados_investimentos(page)
                        for trans in transacoes:
                            trans.update({"agencia": dados_cabecalho.get("agencia"), "conta": dados_cabecalho.get("conta"), "ficheiro_origem": ficheiro_pdf.name})
                            lista_transacoes_finais.append(trans)
        except Exception as e:
            st.error(f"Erro ao processar o PDF {ficheiro_pdf.name}: {e}")
    return pd.DataFrame(lista_transacoes_finais)

# --- INTERFACE DA APLICAÇÃO ---

st.info("Carregue os extratos (PDF) e a sua planilha de movimentação (CSV) para realizar a conciliação.")

col1, col2 = st.columns(2)
with col1:
    extratos_pdf = st.file_uploader("1. Carregar Extratos (PDF)", type="pdf", accept_multiple_files=True)
with col2:
    movimentacao_csv = st.file_uploader("2. Carregar Movimentação Contábil (CSV)", type="csv")

if st.button("Realizar Conciliação", type="primary", use_container_width=True):
    if extratos_pdf and movimentacao_csv:
        with st.spinner("A processar..."):
            df_extratos = processar_extratos_pdf(extratos_pdf)
            df_movimentacao = pd.read_csv(movimentacao_csv, sep=';', decimal=',', encoding='latin1')

            if not df_extratos.empty and not df_movimentacao.empty:
                st.subheader("Diagnóstico do Ficheiro CSV")
                st.write("Colunas encontradas no seu CSV:")
                st.code(f"{df_movimentacao.columns.tolist()}")
                
                try:
                    # --- BLOCO DE CONFIGURAÇÃO ---
                    NOME_DA_COLUNA_CONTA_NO_CSV = 'Conta'
                    NOME_COLUNA_DATA_CSV = 'Data'
                    NOME_COLUNA_VALOR_CSV = 'Valor'
                    # ---------------------------------

                    df_extratos['chave_conta'] = df_extratos['conta'].apply(criar_chave_conta)
                    df_movimentacao['chave_conta'] = df_movimentacao[NOME_DA_COLUNA_CONTA_NO_CSV].apply(criar_chave_conta)
                    
                    df_extratos_std = df_extratos[['data', 'valor', 'chave_conta', 'historico']].copy()
                    df_extratos_std.rename(columns={'data': 'data_movimento'}, inplace=True)
                    
                    df_movimentacao_std = df_movimentacao[[NOME_COLUNA_DATA_CSV, NOME_COLUNA_VALOR_CSV, 'chave_conta']].copy()
                    df_movimentacao_std.rename(columns={NOME_COLUNA_DATA_CSV: 'data_movimento', NOME_COLUNA_VALOR_CSV: 'valor'}, inplace=True)
                    
                    df_extratos_std['valor'] = df_extratos_std['valor'].round(2)
                    df_movimentacao_std['valor'] = df_movimentacao_std['valor'].round(2)

                    df_merged = pd.merge(df_extratos_std, df_movimentacao_std, on=['chave_conta', 'data_movimento', 'valor'], how='outer', indicator=True)
                    
                    st.session_state['conciliados'] = df_merged[df_merged['_merge'] == 'both']
                    st.session_state['apenas_no_extrato'] = df_merged[df_merged['_merge'] == 'left_only']
                    st.session_state['apenas_na_movimentacao'] = df_merged[df_merged['_merge'] == 'right_only']
                    st.success("Conciliação concluída!")

                except KeyError as e:
                    st.error(f"ERRO DE CONFIGURAÇÃO: A coluna {e} não foi encontrada no ficheiro CSV.")
                    st.warning(f"Por favor, edita o ficheiro `app.py`, ajuste a variável que contém {e} no 'BLOCO DE CONFIGURAÇÃO' para que corresponda a um dos nomes de colunas listados acima e envia a alteração para o GitHub.")

            else:
                st.error("Não foi possível extrair transações dos PDFs ou o CSV está vazio.")
    else:
        st.warning("É necessário carregar os ficheiros PDF e o ficheiro CSV para continuar.")

# --- Mostrar Resultados ---
if 'conciliados' in st.session_state:
    st.header("Resultados da Conciliação")
    
    st.subheader(f"✅ Transações Conciliadas ({len(st.session_state.conciliados)})")
    if not st.session_state.conciliados.empty:
        st.dataframe(st.session_state.conciliados.drop(columns=['_merge']))
        
    st.subheader(f"⚠️ Transações Apenas nos Extratos PDF ({len(st.session_state.apenas_no_extrato)})")
    if not st.session_state.apenas_no_extrato.empty:
        st.dataframe(st.session_state.apenas_no_extrato.drop(columns=['_merge']))
        
    st.subheader(f"⚠️ Transações Apenas na Planilha de Movimentação ({len(st.session_state.apenas_na_movimentacao)})")
    if not st.session_state.apenas_na_movimentacao.empty:
        st.dataframe(st.session_state.apenas_na_movimentacao.drop(columns=['_merge']))
