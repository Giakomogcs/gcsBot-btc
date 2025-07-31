import sys
import os
import datetime
import pandas as pd
import joblib
import optuna
import warnings
import logging
import json

# Configurações iniciais
warnings.filterwarnings("ignore", category=UserWarning)
logging.getLogger('lightgbm').setLevel(logging.ERROR)
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Módulos do projeto
from src.config_manager import settings
from src.logger import logger
from src.database_manager import db_manager
from src.core.model_trainer import ModelTrainer
from src.core.situational_awareness import SituationalAwareness

class SituationOptimizer:
    def __init__(self, training_data: pd.DataFrame):
        self.training_data = training_data
        self.trainer = ModelTrainer()
        self.optimizer_settings = settings.optimizer
        self.specialist_definitions = {
            name: spec.features 
            for name, spec in settings.trading_strategy.models.specialists.items()
        }
        logger.info(f"Otimizador configurado para os especialistas: {list(self.specialist_definitions.keys())}")

    def _objective(self, trial: optuna.trial.Trial, data_for_objective: pd.DataFrame, specialist_features: list) -> float:
        params = {
            'objective': 'binary', 'metric': 'binary_logloss', 'verbosity': -1, 'boosting_type': 'gbdt',
            'n_estimators': trial.suggest_int('n_estimators', 100, 1000, log=True),
            'learning_rate': trial.suggest_float('learning_rate', 0.01, 0.3, log=True),
            'num_leaves': trial.suggest_int('num_leaves', 20, 300),
            'max_depth': trial.suggest_int('max_depth', 3, 12),
            'min_child_samples': trial.suggest_int('min_child_samples', 5, 100),
            'feature_fraction': trial.suggest_float('feature_fraction', 0.4, 1.0),
            'bagging_fraction': trial.suggest_float('bagging_fraction', 0.4, 1.0),
            'bagging_freq': trial.suggest_int('bagging_freq', 1, 7),
            'lambda_l1': trial.suggest_float('lambda_l1', 1e-8, 10.0, log=True),
            'lambda_l2': trial.suggest_float('lambda_l2', 1e-8, 10.0, log=True),
        }
        if not all(feat in data_for_objective.columns for feat in specialist_features):
            logger.error(f"Features faltando no trial. Necessárias: {specialist_features}")
            return -1.0
        score = self.trainer.train_and_backtest_for_optimization(data=data_for_objective, params=params, feature_names=specialist_features)
        return score

    def run(self) -> None:
        logger.info("\n" + "="*80 + "\n--- 🚀 INICIANDO OTIMIZAÇÃO POR REGIME DE MERCADO 🚀 ---\n" + "="*80)
        optuna.logging.set_verbosity(optuna.logging.WARNING)
        
        market_regimes = self.training_data['market_regime'].unique()
        logger.info(f"Regimes de mercado encontrados: {market_regimes}")

        for regime_id in market_regimes:
            if regime_id == -1: continue
            regime_id = int(regime_id)
            logger.info(f"\n{'='*25} Otimizando para o REGIME DE MERCADO: {regime_id} {'='*25}")
            
            regime_data = self.training_data[self.training_data['market_regime'] == regime_id].copy()
            if len(regime_data) < 500:
                logger.warning(f"Poucos dados para o regime {regime_id} ({len(regime_data)} amostras). Otimização pulada.")
                continue

            regime_models_path = os.path.join(settings.data_paths.models_dir, f"regime_{regime_id}")
            os.makedirs(regime_models_path, exist_ok=True)

            for specialist_name, specialist_features in self.specialist_definitions.items():
                logger.info(f"--- Otimizando especialista '{specialist_name}' para o regime {regime_id} ---")
                study = optuna.create_study(direction="maximize")
                objective_func = lambda trial: self._objective(trial, regime_data, specialist_features)
                study.optimize(objective_func, n_trials=self.optimizer_settings.n_trials)

                try:
                    best_trial = study.best_trial
                    if best_trial.value > self.optimizer_settings.quality_threshold:
                        logger.info(f"   -> ✅ Score ({best_trial.value:.4f})! Salvando modelo...")
                        final_model = self.trainer.train(regime_data.copy(), best_trial.params, specialist_features)
                        model_path = os.path.join(regime_models_path, f"model_{specialist_name}.joblib")
                        joblib.dump(final_model, model_path)
                    else:
                        logger.warning(f"   -> Score ({best_trial.value:.4f}) não atingiu o limiar. Modelo não salvo.")
                except ValueError:
                    logger.warning("Nenhum trial concluído com sucesso.")
        logger.info("\n" + "="*80 + "\n--- ✅ OTIMIZAÇÃO CONCLUÍDA ✅ ---\n" + "="*80)

# --- INÍCIO DA CORREÇÃO: DEFINIÇÃO DA FUNÇÃO DE DIAGNÓSTICO ---
def check_database_readiness(query_api) -> bool:
    """
    Função de diagnóstico que faz uma consulta leve para verificar se a
    features_master_table está acessível e contém dados.
    """
    logger.info("--- 🔬 Executando diagnóstico da base de dados... ---")
    try:
        # Consulta muito leve: pega apenas o último registo
        diagnostic_query = f'''
        from(bucket:"{settings.database.bucket}") 
            |> range(start: -5y) 
            |> filter(fn: (r) => r._measurement == "features_master_table")
            |> last()
        '''
        result = query_api.query(diagnostic_query)
        if not result or not result[0].records:
            logger.error("Diagnóstico Falhou: A consulta à 'features_master_table' não retornou nenhum resultado.")
            return False
        
        logger.info("✅ Diagnóstico bem-sucedido: A base de dados está acessível e a 'features_master_table' contém dados.")
        return True
    except Exception as e:
        logger.error(f"Diagnóstico Falhou: Ocorreu um erro crítico ao consultar a base de dados: {e}", exc_info=True)
        return False
# --- FIM DA CORREÇÃO ---

def run_optimization():
    """Função principal para carregar dados da DB e executar a otimização."""
    logger.info("Iniciando processo de otimização...")
    
    query_api = db_manager.get_query_api()
    if not query_api:
        logger.error("Otimização abortada: db_manager não disponível.")
        return

    # Passo 1: Executa o diagnóstico antes de tentar carregar a massa de dados
    if not check_database_readiness(query_api):
        logger.critical("A base de dados não está pronta para a otimização. Verifique os logs de diagnóstico e do pipeline 'update-db'.")
        return

    # Passo 2: Se o diagnóstico passar, executa a consulta principal
    logger.info("Carregando dados da Tabela Mestre para o Otimizador (último ano)...")
    query = f'''
    from(bucket:"{settings.database.bucket}") 
        |> range(start: -1y) 
        |> filter(fn: (r) => r._measurement == "features_master_table") 
        |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")
    '''
    df_master = pd.DataFrame()
    try:
        df_master = query_api.query_data_frame(query)
    except Exception as e:
        logger.error(f"Erro crítico durante a consulta principal ao InfluxDB: {e}", exc_info=True)

    if df_master.empty:
        logger.error("A consulta principal não retornou dados, embora o diagnóstico tenha sido bem-sucedido. Verifique se há dados no último ano.")
        return
        
    df_master = df_master.drop(columns=['result', 'table', '_start', '_stop', '_measurement'], errors='ignore')
    df_master.rename(columns={'_time': 'timestamp'}, inplace=True)
    df_master.set_index('timestamp', inplace=True)
    
    logger.info(f"✅ {len(df_master)} registos carregados da Tabela Mestre para treino.")
    optimizer = SituationOptimizer(training_data=df_master)
    optimizer.run()

if __name__ == '__main__':
    # O otimizador só tem uma função agora: otimizar.
    # A lógica de 'train_regime_model' foi movida para o pipeline.
    run_optimization()