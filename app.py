import streamlit as st
import pandas as pd
import pdfplumber
import re
from io import BytesIO

st.set_page_config(layout="wide")
st.title(" ferramenta de Conciliação Bancária")

# --- FUNÇÕES AUXILIARES ---

def criar_chave_conta(numero_conta):
    """Cria uma chave primária a partir de um número de conta, usando os últimos 5 dígitos."""
    try:
        s = str(numero_conta)
        numeros = re.sub(r'\D', '', s)
        chave = numeros[-5:]
        return chave.zfill(5)
    except:
        return None

def limpar_valor(valor_texto):
    """Converte valores monetários em texto para float."""
    if isinstance(valor_texto, str):
        try:
            valor_limpo = re.sub(r'[^\d,]', '', valor_texto).replace(',', '.')
            return float(valor_limpo)
        except (ValueError, AttributeError):
            return 0.0
    return 0.0

# --- FUNÇÕES DE EXTRAÇÃO DE PDF ---

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

def extrair_dados_investimentos(texto):
    if "NÃO HOUVE MOVIMENTO NO PERÍODO SOLICITADO." in texto:
        return [] # Retorna lista vazia se não houver movimento

    transacoes = []
    # Usar regex para encontrar as linhas de transação na tabela de extrato
    # Este padrão busca por linhas que começam com uma data no formato DD/MM/AAAA
    linhas = re.findall(r"(\d{2}/\d{2}/\d{4})\s+(APLICAÇÃO|RESGATE)\s+([\d\.,]+)", texto)
    for data, historico, valor_str in linhas:
        transacoes.append({
            "data": data,
            "historico": historico,
            "valor": limpar_valor(valor_str)
        })
    return transacoes

def processar_extratos_pdf(lista_ficheiros_pdf):
    """
    Nova função para extrair TRANSAÇÕES INDIVIDUAIS dos PDFs.
    """
    lista_transacoes_finais = []
    for ficheiro_pdf in lista_ficheiros_pdf:
        try:
            with pdfplumber.open(ficheiro_pdf) as pdf:
                texto_completo = "".join([pagina.extract_text(x_tolerance=2) or "" for pagina in pdf.pages])
                tipo_extrato = identificar_tipo_extrato(texto_completo)
                
                if tipo_extrato == "INVESTIMENTOS":
                    dados_cabecalho = extrair_dados_cabecalho(texto_completo)
                    transacoes = extrair_dados_investimentos(texto_completo)
                    
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

# Colunas para Upload
col1, col2 = st.columns(2)
with col1:
    extratos_pdf = st.file_uploader("1. Carregar Extratos de Investimentos (PDF)", type="pdf", accept_multiple_files=True)
with col2:
    movimentacao_csv = st.file_uploader("2. Carregar Planilha de Movimentação Contábil (CSV)", type="csv")

if st.button("Realizar Conciliação", type="primary", use_container_width=True):
    if extratos_pdf and movimentacao_csv:
        with st.spinner("A processar... Por favor, aguarde."):
            # Passo 1: Extrair transações dos PDFs
            df_extratos = processar_extratos_pdf(extratos_pdf)
            
            # Passo 2: Carregar a movimentação contábil
            df_movimentacao = pd.read_csv(movimentacao_csv, sep=';', decimal=',', encoding='latin1')

            if not df_extratos.empty and not df_movimentacao.empty:
                # Passo 3: Criar as chaves primárias (como sugeriste)
                # ATENÇÃO: Ajuste 'Nome da Coluna da Conta' para o nome correto no seu CSV
                st.write("A criar chaves de conciliação...")
                df_extratos['chave_conta'] = df_extratos['conta'].apply(criar_chave_conta)
                
                # ADAPTE A LINHA ABAIXO com o nome correto da coluna da conta no seu CSV
                # Exemplo: se a coluna se chamar 'Conta Corrente', use df_movimentacao['Conta Corrente']
                NOME_DA_COLUNA_CONTA_NO_CSV = 'Conta' # <--- AJUSTE AQUI SE NECESSÁRIO
                df_movimentacao['chave_conta'] = df_movimentacao[NOME_DA_COLUNA_CONTA_NO_CSV].apply(criar_chave_conta)

                # Passo 4: Padronizar colunas para o merge
                # ADAPTE os nomes das colunas de data e valor do seu CSV
                df_extratos_std = df_extratos[['data', 'valor', 'chave_conta', 'historico']].copy()
                df_extratos_std.rename(columns={'data': 'data_movimento'}, inplace=True)
                
                # ADAPTE A LINHA ABAIXO com os nomes corretos das colunas no seu CSV
                NOME_COLUNA_DATA_CSV = 'Data' # <--- AJUSTE AQUI
                NOME_COLUNA_VALOR_CSV = 'Valor' # <--- AJUSTE AQUI
                df_movimentacao_std = df_movimentacao[[NOME_COLUNA_DATA_CSV, NOME_COLUNA_VALOR_CSV, 'chave_conta']].copy()
                df_movimentacao_std.rename(columns={NOME_COLUNA_DATA_CSV: 'data_movimento', NOME_COLUNA_VALOR_CSV: 'valor'}, inplace=True)
                
                # Arredondar valores para evitar problemas com casas decimais
                df_extratos_std['valor'] = df_extratos_std['valor'].round(2)
                df_movimentacao_std['valor'] = df_movimentacao_std['valor'].round(2)

                # Passo 5: Realizar a conciliação (merge)
                st.write("A cruzar os dados...")
                df_merged = pd.merge(
                    df_extratos_std,
                    df_movimentacao_std,
                    on=['chave_conta', 'data_movimento', 'valor'],
                    how='outer',
                    indicator=True
                )

                # Passo 6: Separar os resultados
                conciliados = df_merged[df_merged['_merge'] == 'both']
                apenas_no_extrato = df_merged[df_merged['_merge'] == 'left_only']
                apenas_na_movimentacao = df_merged[df_merged['_merge'] == 'right_only']

                # Guardar resultados no estado da sessão para mostrar
                st.session_state['conciliados'] = conciliados
                st.session_state['apenas_no_extrato'] = apenas_no_extrato
                st.session_state['apenas_na_movimentacao'] = apenas_na_movimentacao
                st.success("Conciliação concluída!")

            else:
                st.error("Não foi possível extrair transações dos PDFs ou o CSV está vazio.")

    else:
        st.warning("É necessário carregar os ficheiros PDF e o ficheiro CSV para continuar.")


# --- Mostrar Resultados ---
if 'conciliados' in st.session_state:
    st.header("Resultados da Conciliação")

    st.subheader(f"✅ Transações Conciliadas ({len(st.session_state.conciliados)})")
    st.dataframe(st.session_state.conciliados)

    st.subheader(f"⚠️ Transações Apenas nos Extratos PDF ({len(st.session_state.apenas_no_extrato)})")
    st.dataframe(st.session_state.apenas_no_extrato)

    st.subheader(f"⚠️ Transações Apenas na Planilha de Movimentação ({len(st.session_state.apenas_na_movimentacao)})")
    st.dataframe(st.session_state.apenas_na_movimentacao)
