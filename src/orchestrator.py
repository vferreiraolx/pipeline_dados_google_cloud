"""
Orquestrador do Pipeline de Dados.

Coordena o fluxo completo do pipeline: validação de configuração,
conexão com Trino, extração de dados, upload para GCS, carga no
BigQuery, execução de tabelas derivadas e exportação para Google Sheets.

Nunca interrompe a execução por falhas individuais de tabelas —
registra o erro e continua com as próximas tabelas.
"""

import calendar
import os
from datetime import date
from typing import Optional

from src.bigquery_loader import BigQueryLoader
from src.config_manager import ConfigManager
from src.exceptions import ConfigValidationError, CredentialError
from src.gcs_uploader import GCSUploader
from src.logger import log_step, setup_logger
from src.sheets_exporter import SheetsExporter
from src.state_manager import StateManager
from src.tableau_trigger import trigger_refresh
from src.trino_extractor import TrinoExtractor


class Orchestrator:
    """Coordena o fluxo completo do pipeline de dados.

    Responsável por:
    - Carregar e validar a configuração (ConfigManager).
    - Conectar ao Trino (TrinoExtractor) com retry.
    - Para cada tabela-fonte: verificar estado, extrair (full/incremental),
      fazer upload para GCS e carregar no BigQuery.
    - Executar tabelas derivadas em ordem definida na configuração.
    - Exportar dados para Google Sheets conforme mapeamento.
    - Coletar e reportar lista de tabelas com falha ao final.
    - Retornar relatório de execução (dict com status por etapa).

    O orquestrador NUNCA lança exceção por falha individual de tabela.
    Se a conexão com Trino falhar, aborta a execução com relatório de erro.
    Se a validação de config falhar, aborta com detalhes do erro.

    Attributes:
        config: Instância do ConfigManager com a configuração validada.
    """

    def __init__(self, config: ConfigManager):
        """Inicializa o Orchestrator com a configuração validada.

        Args:
            config: Instância de ConfigManager já carregada e validada.
        """
        self.config = config
        self._logger = setup_logger("orchestrator")

    def run(self, group: str = "all", bootstrap_month: Optional[str] = None) -> dict:
        """Executa o pipeline completo e retorna relatório de execução.

        Fluxo:
            1. Conectar ao Trino (abort se falhar após retries).
            2. Para cada tabela-fonte do grupo solicitado:
               a. Verificar estado (first_load ou incremental).
               b. Extrair dados (full, incremental ou date_range para bootstrap).
               c. Upload para GCS.
               d. Carregar no BigQuery.
               e. Registrar estado de extração.
            3. Fechar conexão Trino.
            4. Executar tabelas derivadas (pulado se bootstrap_month informado).
            5. Exportar para Google Sheets (pulado se bootstrap_month informado).
            6. Retornar relatório.

        Args:
            group: Grupo de cadência — "hourly" (só gold), "daily" (só silver)
                ou "all" (todas as tabelas, comportamento legado).
            bootstrap_month: Quando informado no formato "YYYY-MM", executa o
                bootstrap mensal: extrai apenas tabelas com historical=True
                para o mês especificado e carrega com WRITE_APPEND. Tabelas
                derivadas e exportação Sheets são puladas.

        Returns:
            Dicionário com relatório de execução contendo:
            - overall_status: 'sucesso' ou 'falha_parcial' ou 'falha'
            - tables_processed: lista de tabelas processadas com sucesso
            - tables_failed: lista de tabelas que falharam
            - stages: dict com status de cada etapa principal
        """
        report = {
            "overall_status": "sucesso",
            "tables_processed": [],
            "tables_failed": [],
            "stages": {
                "conexao_trino": "não_executado",
                "extracao": "não_executado",
                "upload_gcs": "não_executado",
                "carga_bigquery": "não_executado",
                "tabelas_derivadas": "não_executado",
                "tableau_trigger": "não_executado",
                "exportacao_sheets": "não_executado",
            },
        }

        # --- Etapa 1: Conexão com Trino ---
        trino = None
        try:
            trino = TrinoExtractor()
        except CredentialError as e:
            log_step(
                "CONEXÃO", "FALHA", "N/A", 0,
                f"Credenciais ausentes: {e}", self._logger,
            )
            report["stages"]["conexao_trino"] = "falha"
            report["overall_status"] = "falha"
            return report

        try:
            trino.connect()
            log_step(
                "CONEXÃO", "SUCESSO", "N/A", 0,
                "Conexão com Trino estabelecida", self._logger,
            )
            report["stages"]["conexao_trino"] = "sucesso"
        except ConnectionError as e:
            log_step(
                "CONEXÃO", "FALHA", "N/A", 0,
                f"Falha na conexão com Trino: {e}", self._logger,
            )
            report["stages"]["conexao_trino"] = "falha"
            report["overall_status"] = "falha"
            return report

        # --- Etapas 2-4: Extração, Upload GCS, Carga BigQuery ---
        try:
            self._process_source_tables(trino, report, group, bootstrap_month=bootstrap_month)
        finally:
            # Sempre fechar conexão Trino
            trino.close()
            log_step(
                "CONEXÃO", "SUCESSO", "N/A", 0,
                "Conexão com Trino fechada", self._logger,
            )

        if bootstrap_month:
            # Bootstrap mensal: pula derivadas e Sheets — dados silver ainda incompletos.
            report["stages"]["tabelas_derivadas"] = "pulado_bootstrap"
            report["stages"]["exportacao_sheets"] = "pulado_bootstrap"
            report["stages"]["tableau_trigger"] = "pulado_bootstrap"
        else:
            # --- Etapa 5: Tabelas derivadas ---
            self._process_derived_tables(report)

            # --- Etapa 6: Trigger Tableau (após derivadas, antes do Sheets) ---
            # Só dispara quando derivadas concluíram sem falhas críticas.
            # Graceful: falha do Tableau não altera overall_status.
            self._trigger_tableau_refresh(report)

            # --- Etapa 7: Exportação para Google Sheets ---
            self._process_sheets_export(report)

        # --- Determinar status geral ---
        if report["tables_failed"]:
            report["overall_status"] = "falha_parcial"

        return report

    def _process_source_tables(
        self,
        trino: TrinoExtractor,
        report: dict,
        group: str = "all",
        bootstrap_month: Optional[str] = None,
    ) -> None:
        """Processa todas as tabelas-fonte do grupo: extração, upload e carga.

        Para cada tabela configurada no grupo:
        - Verifica se é primeira carga ou incremental (respeitando always_full).
        - Extrai dados via Trino.
        - Faz upload para GCS.
        - Carrega no BigQuery.
        - Registra estado no StateManager.

        Quando bootstrap_month é informado, apenas tabelas com historical=True
        são processadas, usando extract_date_range e WRITE_APPEND.

        Em caso de falha em qualquer etapa de uma tabela, registra o erro
        e pula para a próxima tabela.

        Args:
            trino: Instância do TrinoExtractor com conexão ativa.
            report: Dicionário de relatório para atualização.
            group: Grupo de cadência — filtra as tabelas a processar.
            bootstrap_month: Mês no formato "YYYY-MM" para bootstrap mensal.
                Quando informado, processa apenas tabelas históricas para
                aquele mês específico com WRITE_APPEND.
        """
        source_tables = self.config.get_source_tables(group=group)

        # Bootstrap mensal: filtra apenas tabelas históricas e calcula intervalo de datas.
        bootstrap_start: Optional[str] = None
        bootstrap_end: Optional[str] = None
        if bootstrap_month:
            source_tables = [t for t in source_tables if t.historical]
            year, month = int(bootstrap_month[:4]), int(bootstrap_month[5:7])
            bootstrap_start = f"{year}-{month:02d}-01"
            last_day = calendar.monthrange(year, month)[1]
            end_year = year + 1 if month == 12 else year
            end_month = 1 if month == 12 else month + 1
            bootstrap_end = f"{end_year}-{end_month:02d}-01"
            log_step(
                "BOOTSTRAP", "INICIO", "N/A", 0,
                f"Bootstrap mensal {bootstrap_month}: {len(source_tables)} tabela(s) histórica(s), "
                f"intervalo [{bootstrap_start}, {bootstrap_end})",
                self._logger,
            )
        state_manager = StateManager(project=self.config.project_id)
        gcs_uploader = GCSUploader(
            project=self.config.project_id,
            bucket_name=self.config.bucket_name,
        )
        bq_loader = BigQueryLoader(project=self.config.project_id)

        extraction_ok = True
        upload_ok = True
        load_ok = True

        today = date.today()
        today_str = today.strftime("%Y-%m-%d")

        for table_cfg in source_tables:
            table_name = table_cfg.short_name
            full_name = table_cfg.full_name
            partition_column = table_cfg.partition_column

            try:
                # Verificar estado
                is_first = state_manager.is_first_load(table_name)

                # Definir caminho de saída local
                output_dir = "tmp"
                os.makedirs(output_dir, exist_ok=True)
                local_path = os.path.join(
                    output_dir, f"{table_name}_{today_str}.csv"
                )

                # Extração
                log_step(
                    "EXTRAÇÃO", "INICIO", table_name, 0,
                    f"Iniciando extração {'custom' if table_cfg.sql_file else 'completa' if is_first else 'incremental'}",
                    self._logger,
                )

                if bootstrap_month and bootstrap_start and bootstrap_end and partition_column:
                    # Bootstrap mensal: extrai apenas o mês solicitado (~≤100K linhas).
                    # Usa WRITE_APPEND no BQ para acumular meses sem truncar os anteriores.
                    log_step(
                        "EXTRAÇÃO", "INICIO", table_name, 0,
                        f"Bootstrap {bootstrap_month}: [{bootstrap_start}, {bootstrap_end})",
                        self._logger,
                    )
                    rows = trino.extract_date_range(
                        full_name, partition_column, bootstrap_start, bootstrap_end, local_path
                    )
                    extraction_type = "bootstrap"
                elif table_cfg.sql_file:
                    # Extração com SQL customizado
                    sql_path = os.path.join(
                        os.path.dirname(os.path.abspath(self.config._config_path))
                        if hasattr(self.config, "_config_path") else ".",
                        table_cfg.sql_file,
                    )
                    with open(sql_path, "r", encoding="utf-8") as f:
                        custom_query = f.read()
                    rows = trino.extract_custom(custom_query, local_path)
                    extraction_type = "full"
                elif table_cfg.always_full and partition_column:
                    # Extração completa por partição: evita OOM em tabelas históricas grandes.
                    # SELECT * único carregaria 1.25M+ linhas em memória Python; aqui
                    # iteramos partição a partição mantendo footprint constante.
                    log_step(
                        "EXTRAÇÃO", "DEBUG", table_name, 0,
                        f"[DIAGNÓSTICO] always_full=True, partition_col='{partition_column}' "
                        f"→ usando extract_full_by_partitions",
                        self._logger,
                    )
                    rows = trino.extract_full_by_partitions(
                        full_name, partition_column, local_path
                    )
                    extraction_type = "full"
                elif is_first or table_cfg.use_max_dt or table_cfg.always_full:
                    rows = trino.extract_full(full_name, local_path)
                    extraction_type = "full"
                else:
                    rows = trino.extract_incremental(
                        full_name, partition_column, local_path
                    )
                    extraction_type = "incremental"

                log_step(
                    "EXTRAÇÃO", "SUCESSO", table_name, rows,
                    f"Extração {extraction_type} concluída",
                    self._logger,
                )

            except Exception as e:
                log_step(
                    "EXTRAÇÃO", "FALHA", table_name, 0,
                    f"Erro na extração: {e}", self._logger,
                )
                report["tables_failed"].append(
                    {"table": table_name, "stage": "extração", "error": str(e)}
                )
                extraction_ok = False
                continue

            # Tabelas horárias (gold) com 0 linhas: pula carga para não apagar
            # a partição existente do dia anterior — preserva histórico no Tableau.
            if rows == 0 and table_cfg.group == "hourly":
                log_step(
                    "CARGA_BQ", "SKIP", table_name, 0,
                    "Zero linhas extraídas (Trino sem dados para hoje) — "
                    "partição anterior preservada, carga ignorada",
                    self._logger,
                )
                state_manager.mark_loaded(
                    table_name=table_name,
                    load_date=today_str,
                    rows_count=0,
                    extraction_type=extraction_type,
                    status="skip_zero_rows",
                )
                report["tables_processed"].append(table_name)
                continue

            # Upload para GCS
            try:
                gcs_path = gcs_uploader.build_gcs_path(table_name, today)
                gcs_uri = f"gs://{self.config.bucket_name}/{gcs_path}"

                log_step(
                    "UPLOAD_GCS", "INICIO", table_name, 0,
                    f"Enviando para {gcs_uri}", self._logger,
                )

                gcs_uploader.upload(local_path, gcs_path)

                log_step(
                    "UPLOAD_GCS", "SUCESSO", table_name, rows,
                    "Upload concluído", self._logger,
                )

            except Exception as e:
                log_step(
                    "UPLOAD_GCS", "FALHA", table_name, 0,
                    f"Erro no upload GCS: {e}", self._logger,
                )
                report["tables_failed"].append(
                    {"table": table_name, "stage": "upload_gcs", "error": str(e)}
                )
                upload_ok = False
                continue

            # Carga no BigQuery
            try:
                dataset = self.config.config.get("bigquery", {}).get(
                    "dataset", "planejamento_comercial"
                )
                table_id = f"{self.config.project_id}.{dataset}.{table_name}"

                log_step(
                    "CARGA_BQ", "INICIO", table_name, 0,
                    f"Carregando em {table_id} (modo: {extraction_type})",
                    self._logger,
                )

                if extraction_type == "bootstrap":
                    # Bootstrap mensal: WRITE_APPEND acumula meses sem truncar anteriores.
                    bq_loader.load_append(gcs_uri, table_id, partition_column)
                elif extraction_type == "full":
                    bq_loader.load_full(gcs_uri, table_id)
                elif table_cfg.historical:
                    # Tabela histórica: WRITE_APPEND para preservar dados acumulados.
                    bq_loader.load_append(gcs_uri, table_id, partition_column)
                elif table_cfg.group == "hourly":
                    # Tabela horária (gold): substitui apenas a partição de hoje.
                    # WRITE_TRUNCATE total apagaria todo o histórico quando Trino
                    # não tem dados do dia corrente; partition load preserva ontem.
                    bq_loader.load_partition(gcs_uri, table_id, today)
                else:
                    bq_loader.load_incremental(
                        gcs_uri, table_id, partition_column
                    )

                log_step(
                    "CARGA_BQ", "SUCESSO", table_name, rows,
                    f"Carga {extraction_type} concluída", self._logger,
                )

                # Registrar estado
                state_manager.mark_loaded(
                    table_name=table_name,
                    load_date=today_str,
                    rows_count=rows,
                    extraction_type=extraction_type,
                    status="success",
                )

                report["tables_processed"].append(table_name)

            except Exception as e:
                log_step(
                    "CARGA_BQ", "FALHA", table_name, 0,
                    f"Erro na carga BigQuery: {e}", self._logger,
                )
                report["tables_failed"].append(
                    {"table": table_name, "stage": "carga_bigquery", "error": str(e)}
                )
                load_ok = False
                continue

        # Atualizar status das etapas no relatório
        report["stages"]["extracao"] = "sucesso" if extraction_ok else "falha_parcial"
        report["stages"]["upload_gcs"] = "sucesso" if upload_ok else "falha_parcial"
        report["stages"]["carga_bigquery"] = "sucesso" if load_ok else "falha_parcial"

    def _process_derived_tables(self, report: dict) -> None:
        """Executa tabelas derivadas em ordem definida na configuração.

        Lê o arquivo SQL de cada tabela derivada e executa via BigQueryLoader.
        Em caso de falha, registra o erro e continua com as demais.

        Args:
            report: Dicionário de relatório para atualização.
        """
        derived_tables = self.config.get_derived_tables()
        bq_loader = BigQueryLoader(project=self.config.project_id)
        all_ok = True

        for dt_cfg in derived_tables:
            try:
                # Ler arquivo SQL
                sql_path = dt_cfg.sql_file
                if not os.path.isabs(sql_path):
                    # Caminho relativo ao diretório do config
                    sql_path = os.path.join(
                        os.path.dirname(
                            os.path.abspath(self.config._config_path)
                        )
                        if hasattr(self.config, "_config_path")
                        else ".",
                        sql_path,
                    )

                # Se o caminho ainda não existe, tentar na raiz do projeto
                if not os.path.isfile(sql_path):
                    sql_path = dt_cfg.sql_file

                with open(sql_path, "r", encoding="utf-8") as f:
                    query = f.read()

                log_step(
                    "TABELA_DERIVADA", "INICIO", dt_cfg.name, 0,
                    f"Executando transformação para {dt_cfg.destination}",
                    self._logger,
                )

                bq_loader.execute_derived_table(query, dt_cfg.destination)

                log_step(
                    "TABELA_DERIVADA", "SUCESSO", dt_cfg.name, 0,
                    f"Tabela derivada {dt_cfg.name} criada com sucesso",
                    self._logger,
                )

            except Exception as e:
                log_step(
                    "TABELA_DERIVADA", "FALHA", dt_cfg.name, 0,
                    f"Erro na tabela derivada: {e}", self._logger,
                )
                report["tables_failed"].append(
                    {"table": dt_cfg.name, "stage": "tabela_derivada", "error": str(e)}
                )
                all_ok = False

        report["stages"]["tabelas_derivadas"] = "sucesso" if all_ok else "falha_parcial"

    def _trigger_tableau_refresh(self, report: dict) -> None:
        """Dispara refresh da fonte de dados no Tableau Cloud após derivadas.

        Graceful degradation: falha aqui nunca propaga nem altera overall_status.
        Quando TABLEAU_DATASOURCE_ID não está configurado, etapa é marcada como
        'não_configurado' e execução continua normalmente.

        Args:
            report: Dicionário de relatório para atualização do stage.
        """
        datasource_id = os.getenv("TABLEAU_DATASOURCE_ID", "")
        result = trigger_refresh(datasource_id)

        if not datasource_id:
            report["stages"]["tableau_trigger"] = "não_configurado"
        elif result.triggered:
            report["stages"]["tableau_trigger"] = "sucesso"
            report["tableau_trigger_job_id"] = result.job_id
        else:
            report["stages"]["tableau_trigger"] = "falha"
            report["tableau_trigger_error"] = result.error
            # NÃO adiciona em tables_failed — Tableau é best-effort,
            # não deve degradar o overall_status do pipeline de dados.

    def _process_sheets_export(self, report: dict) -> None:
        """Exporta dados para Google Sheets conforme mapeamentos configurados.

        Para cada mapeamento, exporta a tabela BigQuery para a aba
        correspondente na planilha. Em caso de falha, registra o erro
        e continua com as demais exportações.

        Args:
            report: Dicionário de relatório para atualização.
        """
        mappings = self.config.get_sheets_mappings()
        all_ok = True

        try:
            exporter = SheetsExporter()
        except Exception as e:
            log_step(
                "EXPORTAÇÃO_SHEETS", "FALHA", "N/A", 0,
                f"Erro ao inicializar SheetsExporter: {e}", self._logger,
            )
            report["stages"]["exportacao_sheets"] = "falha"
            # Registrar todas as tabelas como falha
            for mapping in mappings:
                report["tables_failed"].append(
                    {"table": mapping.table, "stage": "exportacao_sheets", "error": str(e)}
                )
            return

        for mapping in mappings:
            try:
                log_step(
                    "EXPORTAÇÃO_SHEETS", "INICIO", mapping.table, 0,
                    f"Exportando para planilha {mapping.spreadsheet_id} "
                    f"aba '{mapping.sheet_name}'",
                    self._logger,
                )

                exporter.export(
                    table_id=mapping.table,
                    spreadsheet_id=mapping.spreadsheet_id,
                    sheet_name=mapping.sheet_name,
                )

                log_step(
                    "EXPORTAÇÃO_SHEETS", "SUCESSO", mapping.table, 0,
                    f"Exportação concluída para aba '{mapping.sheet_name}'",
                    self._logger,
                )

            except Exception as e:
                log_step(
                    "EXPORTAÇÃO_SHEETS", "FALHA", mapping.table, 0,
                    f"Erro na exportação: {e}", self._logger,
                )
                report["tables_failed"].append(
                    {"table": mapping.table, "stage": "exportacao_sheets", "error": str(e)}
                )
                all_ok = False

        report["stages"]["exportacao_sheets"] = "sucesso" if all_ok else "falha_parcial"
