# GCS-Bot - Guia de Comandos

Este documento detalha os comandos disponíveis através do script `.\manage.ps1`, que é a principal forma de interagir com o ambiente do GCS-Bot.

## Gestão do Ambiente

Comandos para configurar, iniciar, parar e resetar o ambiente Docker e o banco de dados.

- `.\manage.ps1 setup`
  - **Função**: Configura o ambiente Docker completo pela primeira vez. Constrói as imagens dos containers e prepara tudo para a execução.
  - **Quando usar**: Apenas na primeira vez que for configurar o projeto.

- `.\manage.ps1 start-services`
  - **Função**: Inicia os containers Docker necessários (aplicação e banco de dados) em segundo plano.
  - **Quando usar**: Para iniciar o ambiente depois de tê-lo parado com `stop-services`.

- `.\manage.ps1 stop-services`
  - **Função**: Para todos os containers Docker relacionados ao bot.
  - **Quando usar**: Quando quiser desligar o ambiente do bot.

- `.\manage.ps1 reset-db`
  - **Função**: **AÇÃO DESTRUTIVA.** Para e apaga completamente o volume de dados do banco de dados (InfluxDB). Todo o histórico de mercado e trades será perdido.
  - **Quando usar**: Se o banco de dados estiver corrompido ou se você quiser começar com uma base de dados completamente limpa.

- `.\manage.ps1 clean-master`
  - **Função**: **AÇÃO DESTRUTIVA.** Apaga apenas a tabela principal de features (`features_master_table`), mantendo os dados brutos de mercado. Em seguida, executa o pipeline de dados (`update-db`) para recriá-la.
  - **Quando usar**: Se você modificou a lógica de criação de features e precisa reconstruir a tabela master.

- `.\manage.ps1 reset-trades`
  - **Função**: **AÇÃO DESTRUTIVA.** Apaga apenas o histórico de trades, mantendo todos os dados de mercado e features.
  - **Quando usar**: Para iniciar um novo backtest ou sessão de trading sem o histórico de operações antigas.

## Operações do Bot

Comandos para treinar, testar e executar o bot.

- `.\manage.ps1 update-db`
  - **Função**: Executa o pipeline de ETL (Extração, Transformação e Carga) para baixar os dados de mercado mais recentes, calcular features e salvá-los no banco de dados.
  - **Quando usar**: Regularmente para manter o banco de dados atualizado antes de rodar backtests ou o bot ao vivo.

- `.\manage.ps1 optimize`
  - **Função**: Executa o processo de otimização de estratégias e treinamento de modelos de machine learning.
  - **Quando usar**: Quando você quiser encontrar os melhores parâmetros para sua estratégia ou treinar novos modelos com dados atualizados.

- `.\manage.ps1 backtest`
  - **Função**: Executa um backtest (simulação histórica) usando os dados do banco de dados e a estratégia/modelo configurado.
  - **Quando usar**: Para avaliar a performance de uma estratégia com dados históricos.

- `.\manage.ps1 run-live`
  - **Função**: Inicia o bot em modo de operação real (seja em paper trading ou com dinheiro real, dependendo da sua configuração).
  - **Quando usar**: Quando estiver pronto para operar no mercado.

- `.\manage.ps1 test`
  - **Função**: Executa a suíte de testes automatizados (pytest) para verificar a integridade do código.
  - **Quando usar**: Após fazer alterações no código para garantir que nenhuma funcionalidade existente foi quebrada.

- `.\manage.ps1 analyze`
  - **Função**: Executa um script que analisa e exibe os resultados do último backtest.
  - **Quando usar**: Após um backtest para obter um relatório detalhado da performance.
