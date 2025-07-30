import pandas as pd
import numpy as np
import os
from tqdm import tqdm

from src.core.ensemble_manager import EnsembleManager
from src.core.position_manager import PositionManager
from src.logger import logger # Importar o logger

class Backtester:
    def __init__(self, config, data, ensemble_manager):
        self.config = config
        self.data = data
        self.ensemble_manager = ensemble_manager
        self.position_manager = PositionManager(config)

        # --- INÍCIO DA MODIFICAÇÃO 2: DIAGNÓSTICO DE COLUNAS ---
        # Logar as colunas disponíveis para nos ajudar a depurar o aviso de 'Features faltando'
        logger.info(f"Colunas disponíveis para o backtest: {self.data.columns.to_list()}")
        # --- FIM DA MODIFICAÇÃO 2 ---

    def run(self):
        logger.info("Iniciando backtest...")
        
        confidence_log = []
        trades = []
        
        for i in tqdm(range(1, len(self.data)), desc="Processando velas"):
            current_candle_index = i
            current_candle = self.data.iloc[current_candle_index]
            
            self.position_manager.update_open_positions(current_candle)
            
            closed_trades = self.position_manager.check_and_close_positions(current_candle)
            trades.extend(closed_trades)

            # Passa a fatia de dados necessária para o ensemble
            data_slice = self.data.iloc[:current_candle_index + 1]
            final_confidence, specialist_predictions = self.ensemble_manager.get_prediction(data_slice)

            # --- INÍCIO DA MODIFICAÇÃO 1: CORREÇÃO DO KEYERROR ---
            # O timestamp agora é o NOME (índice) da linha, não uma coluna.
            log_entry = {
                'timestamp': current_candle.name,
                'close': current_candle['close'],
                'final_confidence': final_confidence,
                'signal': specialist_predictions.get('signal')
            }
            # --- FIM DA MODIFICAÇÃO 1 ---

            for specialist_name, prediction_details in specialist_predictions.get('details', {}).items():
                log_entry[f'{specialist_name}_confidence'] = prediction_details.get('confidence')
                log_entry[f'{specialist_name}_weight'] = self.ensemble_manager.weights.get(specialist_name)

            confidence_log.append(log_entry)

            if not self.position_manager.is_position_open():
                signal = specialist_predictions.get('signal')
                if final_confidence >= self.config.trading_strategy.confidence_threshold:
                    if signal == 'LONG':
                        self.position_manager.open_position(
                            entry_candle=current_candle,
                            signal='LONG'
                        )
                    elif signal == 'SHORT':
                        self.position_manager.open_position(
                            entry_candle=current_candle,
                            signal='SHORT'
                        )

        logger.info("Salvando o histórico de confiança...")
        output_path = 'data/output'
        os.makedirs(output_path, exist_ok=True)
        
        log_df = pd.DataFrame(confidence_log)
        log_filepath = os.path.join(output_path, 'confidence_history.csv')
        log_df.to_csv(log_filepath, index=False)
        
        logger.info(f"Histórico de confiança salvo com sucesso em: {log_filepath}")
        
        trades_df = pd.DataFrame(trades)
        return trades_df

    def calculate_metrics(self, trades_df):
        if trades_df.empty:
            return {"message": "Nenhum trade foi executado."}

        total_trades = len(trades_df)
        winning_trades = trades_df[trades_df['pnl'] > 0]
        losing_trades = trades_df[trades_df['pnl'] <= 0]
        
        win_rate = len(winning_trades) / total_trades if total_trades > 0 else 0
        total_pnl = trades_df['pnl'].sum()
        
        profit_factor = abs(winning_trades['pnl'].sum() / losing_trades['pnl'].sum()) if losing_trades['pnl'].sum() != 0 else np.inf
        
        return {
            "Total de Trades": total_trades,
            "Trades Vencedores": len(winning_trades),
            "Trades Perdedores": len(losing_trades),
            "Taxa de Acerto (%)": f"{win_rate * 100:.2f}",
            "Lucro/Prejuízo Total": f"{total_pnl:.4f}",
            "Profit Factor": f"{profit_factor:.2f}"
        }