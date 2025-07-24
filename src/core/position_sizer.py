# src/core/position_sizer.py

from src.config_manager import settings
from src.logger import logger

class DynamicPositionSizer:
    """
    Calcula o tamanho da posição de forma dinâmica com base no capital,
    volatilidade e confiança do modelo.
    """
    def __init__(self):
        # Carrega os parâmetros de configuração
        self.base_risk_percentage = settings.backtest.base_risk_percentage
        self.stop_mult = settings.backtest.stop_mult
        self.max_leverage_pct = settings.backtest.max_leverage_percentage
        self.min_trade_size_usdt = 10.0 # Valor mínimo para uma ordem na Binance

    def calculate_trade_size(self, current_equity: float, atr: float, confidence_score: float) -> float:
        """
        Calcula o valor em USDT a ser investido no próximo trade.
        """
        if atr == 0:
            return 0.0 # Evita divisão por zero se o ATR for nulo

        # 1. Risco Base: Começa com uma % do capital total.
        risk_capital = current_equity * (self.base_risk_percentage / 100.0)

        # 2. Ajuste pela Confiança: Aumenta o risco se a confiança do modelo for alta.
        #    Um score de 0.5 (neutro) não ajusta, acima aumenta, abaixo diminui.
        confidence_factor = 1 + ((confidence_score - 0.5) * 2) # Mapeia [0, 1] para [0, 2]
        adjusted_risk_capital = risk_capital * confidence_factor
        
        # 3. Ajuste pela Volatilidade (ATR): Usa menos capital em mercados mais voláteis.
        #    A posição é: Capital a arriscar / Distância percentual para o stop.
        stop_loss_distance_pct = (atr * self.stop_mult) / self.initial_capital # Simplificação
        if stop_loss_distance_pct == 0:
             return 0.0
             
        position_size = adjusted_risk_capital / stop_loss_distance_pct

        # 4. Limita o tamanho do trade para não exceder um máximo prático
        max_trade_size = current_equity * (self.max_leverage_pct / 100.0)
        
        final_trade_size = min(position_size, max_trade_size)

        # 5. Garante que o trade tem o tamanho mínimo requerido pela exchange
        if final_trade_size < self.min_trade_size_usdt:
            return 0.0

        logger.debug(f"Position Sizer: Equity={current_equity:.2f}, ATR={atr:.2f}, Confidence={confidence_score:.2f} -> Trade Size={final_trade_size:.2f} USDT")

        return final_trade_size