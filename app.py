import streamlit as st
import pandas as pd
import pdfplumber
import re
from io import BytesIO

st.set_page_config(layout="wide")
st.title(" ferramenta de Conciliação Bancária (Modo de Diagnóstico)")

# --- FUNÇÕES AUXILIARES ---

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

# --- FUNÇÕES DE EXTRAÇÃO DE PDF (COM DIAGNÓSTICOS) ---

def identificar_tipo_extrato(texto):
    if "Investimentos Fundos" in texto: return "INVESTIMENTOS"
    if "Extrato de Conta Corrente" in texto: return "CONTA_CORRENTE"
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
    """(VERSÃO DE DIAGNÓSTICO) Extrai transações e imprime o que encontra."""
    transacoes = []
    
    # --- INÍCIO DO CÓDIGO DE DIAGNÓSTICO ---
    st.write(f"--- Diagnóstico da Página {pdf_page.page_number} ---")
    tabelas = pdf_page.extract_tables()
    st.write(f"📄 Encontradas {len(tabelas)} tabelas nesta página.")
    # --- FIM DO CÓDIGO DE DIAGNÓSTICO ---
    
    for i, tabela in enumerate(tabelas):
        # --- INÍCIO DO CÓDIGO DE DIAGNÓSTICO ---
        st.write(f"Tabela {i+1}: Amostra das primeiras 3 linhas:")
        for j, linha_raw in enumerate(tabela[:3]):
            st.text(f"  Linha {j}: {linha_raw}")
        # --- FIM DO CÓDIGO DE DIAGNÓSTICO ---

        for linha in tabela:
            if len(linha) > 2 and linha[1] and isinstance(linha[1], str) and linha[1].strip() in ("APLICAÇÃO", "RESGATE"):
                try:
                    data = linha[0]
                    historico = linha[1].strip()
                    valor_str = linha[2]
                    
                    transacoes.append({
                        "data": data,
                        "historico": historico,
                        "valor": limpar_valor(valor_str)
                    })
                except (IndexError, TypeError):
                    continue
    return transacoes

def processar_extratos_pdf(lista_ficheiros_pdf):
    lista_transacoes_finais = []
    for ficheiro_pdf in lista_ficheiros_pdf:
        st.info(f"🔍 Analisando o ficheiro: {ficheiro_pdf.name}")
        try:
            with pdfplumber.open(ficheiro_pdf) as pdf:
                for page in pdf.pages:
                    texto_completo = page.extract_text(x_tolerance=2) or ""
                    tipo_extrato = identificar_tipo_extrato(texto_completo)
                    
                    if tipo_extrato == "INVESTIMENTOS":
                        dados_cabecalho = extrair_dados_cabecalho(texto_completo)
                        transacoes = extrair_dados_investimentos(page)
                        
                        for trans in transacoes:
                            trans["agencia"] = dados_cabecalho.get("agencia")
                            trans["conta"] = dados_cabecalho.get("conta")
                            trans["ficheiro_origem"] = ficheiro_pdf.name
                            lista_transacoes_finais.append(trans)
        except Exception as e:
            st.error(f"Erro ao processar o PDF {ficheiro_pdf.name}: {e}")
    
    return pd.DataFrame(lista_transacoes_finais)

# --- INTERFACE DA APLICAÇÃO ---

st.info("Carregue os extratos (PDF) e a sua planilha de movimentação (CSV) para realizar a conciliação.")

col1, col2 = st.columns(2)
with col1:
    extratos_pdf = st.file_uploader("1. Carregar Extratos de Investimentos (PDF)", type="pdf", accept_multiple_files=True)
with col2:
    movimentacao_csv = st.file_uploader("2. Carregar Planilha de Movimentação Contábil (CSV)", type="csv")

if st.button("Realizar Conciliação", type="primary", use_container_width=True):
    if extratos_pdf and movimentacao_csv:
        with st.spinner("A processar... Por favor, aguarde."):
            df_extratos = processar_extratos_pdf(extratos_pdf)
            df_movimentacao = pd.read_csv(movimentacao_csv, sep=';', decimal=',', encoding='latin1')

            # --- INÍCIO DO CÓDIGO DE DIAGNÓSTICO ---
            st.header("Relatório de Diagnóstico")
            if df_extratos.empty:
                st.error("RESULTADO DO DIAGNÓSTICO: Nenhuma transação foi extraída dos ficheiros PDF.")
            else:
                st.success(f"RESULTADO DO DIAGNÓSTICO: {len(df_extratos)} transações extraídas dos PDFs com sucesso.")

            if df_movimentacao.empty:
                st.error("RESULTADO DO DIAGNÓSTICO: O ficheiro CSV foi lido mas resultou numa tabela vazia.")
            else:
                st.success(f"RESULTADO DO DIAGNÓSTICO: {len(df_movimentacao)} linhas lidas do CSV com sucesso.")
            # --- FIM DO CÓDIGO DE DIAGNÓSTICO ---

            if not df_extratos.empty and not df_movimentacao.empty:
                # O resto da lógica de conciliação continua aqui...
                st.write("A criar chaves de conciliação...")
                df_extratos['chave_conta'] = df_extratos['conta'].apply(criar_chave_conta)
                NOME_DA_COLUNA_CONTA_NO_CSV = 'Conta' 
                df_movimentacao['chave_conta'] = df_movimentacao[NOME_DA_COLUNA_CONTA_NO_CSV].apply(criar_chave_conta)
                st.write("A padronizar colunas...")
                df_extratos_std = df_extratos[['data', 'valor', 'chave_conta', 'historico']].copy()
                df_extratos_std.rename(columns={'data': 'data_movimento'}, inplace=True)
                NOME_COLUNA_DATA_CSV = 'Data'
                NOME_COLUNA_VALOR_CSV = 'Valor'
                df_movimentacao_std = df_movimentacao[[NOME_COLUNA_DATA_CSV, NOME_COLUNA_VALOR_CSV, 'chave_conta']].copy()
                df_movimentacao_std.rename(columns={NOME_COLUNA_DATA_CSV: 'data_movimento', NOME_COLUNA_VALOR_CSV: 'valor'}, inplace=True)
                df_extratos_std['valor'] = df_extratos_std['valor'].round(2)
                df_movimentacao_std['valor'] = df_movimentacao_std['valor'].round(2)
                st.write("A cruzar os dados...")
                df_merged = pd.merge(df_extratos_std, df_movimentacao_std, on=['chave_conta', 'data_movimento', 'valor'], how='outer', indicator=True)
                st.session_state['conciliados'] = df_merged[df_merged['_merge'] == 'both']
                st.session_state['apenas_no_extrato'] = df_merged[df_merged['_merge'] == 'left_only']
                st.session_state['apenas_na_movimentacao'] = df_merged[df_merged['_merge'] == 'right_only']
                st.success("Conciliação concluída!")
            else:
                 st.error("A conciliação não pode prosseguir porque um dos ficheiros não retornou dados.")
    else:
        st.warning("É necessário carregar os ficheiros PDF e o ficheiro CSV para continuar.")

# --- Mostrar Resultados ---
if 'conciliados' in st.session_state:
    st.header("Resultados da Conciliação")
    # ... (o resto do código para mostrar os resultados continua igual)
