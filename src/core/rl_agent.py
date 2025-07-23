# src/rl_agent.py

import numpy as np
import pandas as pd

class BetSizingAgent:
    def __init__(self, n_situations, n_confidence_levels=10, n_bet_sizes=5, learning_rate=0.1, discount_factor=0.9, exploration_rate=0.1):
        self.n_situations = n_situations
        self.n_confidence_levels = n_confidence_levels
        self.n_bet_sizes = n_bet_sizes
        self.learning_rate = learning_rate
        self.discount_factor = discount_factor
        self.exploration_rate = exploration_rate

        self.q_table = np.zeros((n_situations, n_confidence_levels, n_bet_sizes))

        self.bet_sizes = np.linspace(0.1, 1.0, n_bet_sizes)

    def get_state(self, situation, confidence):
        confidence_level = int(confidence * self.n_confidence_levels)
        return situation, confidence_level

    def get_action(self, state):
        if np.random.uniform(0, 1) < self.exploration_rate:
            return np.random.choice(self.n_bet_sizes)
        else:
            return np.argmax(self.q_table[state])

    def get_bet_size(self, action):
        return self.bet_sizes[action]

    def update_q_table(self, state, action, reward, next_state):
        old_value = self.q_table[state][action]
        next_max = np.max(self.q_table[next_state])

        new_value = (1 - self.learning_rate) * old_value + self.learning_rate * (reward + self.discount_factor * next_max)
        self.q_table[state][action] = new_value
