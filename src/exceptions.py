"""
Exceções customizadas do Pipeline de Dados.

Define as exceções utilizadas para sinalizar erros de configuração
e credenciais em todo o pipeline.
"""


class ConfigValidationError(Exception):
    """Erro de validação do arquivo de configuração.

    Lançado quando o config.yaml contém erros de sintaxe,
    campos obrigatórios ausentes ou referências inválidas.

    A mensagem é sempre em português, indicando:
    - O arquivo com problema
    - O campo ou seção com erro
    - A correção esperada
    """

    pass


class CredentialError(Exception):
    """Erro de credenciais ausentes ou inválidas.

    Lançado quando variáveis de ambiente obrigatórias para
    autenticação (ex: TRINO_USER, TRINO_PASSWORD) estão
    ausentes ou vazias.

    A mensagem indica quais variáveis estão faltando.
    """

    pass
