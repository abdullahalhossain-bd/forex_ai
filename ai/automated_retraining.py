"""
Automated Model Retraining System
Handles scheduled retraining, performance monitoring, and automatic updates

NOTE: TensorFlow, sklearn, and schedule are OPTIONAL dependencies.
      If they are not installed, this module gracefully degrades.
"""
import os
import json
import logging
import time
from datetime import datetime, timedelta
from typing import Dict, Optional
import pandas as pd
import numpy as np

# Optional ML dependencies — the system works without them
try:
    import schedule
    SCHEDULE_AVAILABLE = True
except ImportError:
    SCHEDULE_AVAILABLE = False

try:
    from sklearn.model_selection import TimeSeriesSplit
    from sklearn.metrics import mean_squared_error, mean_absolute_error
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False

try:
    import tensorflow as tf
    from tensorflow import keras
    TF_AVAILABLE = True
except ImportError:
    TF_AVAILABLE = False

from config import Config
from data.automated_updater import data_updater
from ai.model_versioning import model_manager

class AutomatedRetrainingSystem:
    """Automated model retraining with performance monitoring"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.config = Config()
        self.retraining_interval = self.config.RETRAINING_INTERVAL  # e.g., 7 days
        self.performance_threshold = self.config.PERFORMANCE_THRESHOLD
        self.min_training_samples = self.config.MIN_TRAINING_SAMPLES
        
    def start_scheduled_retraining(self):
        """Start scheduled retraining job"""
        if not SCHEDULE_AVAILABLE:
            self.logger.warning("schedule package not installed — scheduled retraining disabled")
            return
        schedule.every(self.retraining_interval).days.do(self._retrain_models)
        
        self.logger.info(f"Scheduled model retraining every {self.retraining_interval} days")
        
        # Run in a separate thread
        import threading
        thread = threading.Thread(target=self._run_scheduler, daemon=True)
        thread.start()
    
    def _run_scheduler(self):
        """Run the scheduler in a loop"""
        while True:
            schedule.run_pending()
            time.sleep(60)  # Check every minute
    
    def _retrain_models(self):
        """Retrain all models with latest data"""
        self.logger.info("Starting automated model retraining")
        
        try:
            # Update data first
            data_status = data_updater.update_all_pairs()
            
            # Check if data update was successful
            if not all(data_status.values()):
                self.logger.error("Data update failed - skipping retraining")
                return False
            
            # Get latest data
            all_data = self._load_all_forex_data()
            
            if all_data.empty:
                self.logger.error("No data available for retraining")
                return False
            
            # Train models
            model_results = {}
            
            for pair in self.config.FOREX_PAIRS:
                try:
                    result = self._train_model_for_pair(pair, all_data)
                    model_results[pair] = result
                except Exception as e:
                    self.logger.error(f"Error training model for {pair}: {e}")
                    model_results[pair] = {'success': False, 'error': str(e)}
            
            # Evaluate and deploy best models
            self._evaluate_and_deploy_models(model_results)
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error in automated retraining: {e}")
            return False
    
    def _load_all_forex_data(self) -> pd.DataFrame:
        """Load all available forex data"""
        all_data = {}
        
        for pair in self.config.FOREX_PAIRS:
            data = data_updater.load_existing_data(pair)
            if not data.empty:
                all_data[pair] = data
        
        if not all_data:
            return pd.DataFrame()
        
        # Combine all data
        combined = pd.DataFrame()
        
        for pair, data in all_data.items():
            # Add prefix to columns
            prefixed_data = data.add_prefix(f"{pair.replace('/', '_')}_")
            combined = pd.concat([combined, prefixed_data], axis=1)
        
        return combined
    
    def _train_model_for_pair(self, pair: str, all_data: pd.DataFrame) -> Dict:
        """Train a model for a specific currency pair"""
        try:
            # Prepare features and target
            pair_col = f"{pair.replace('/', '_')}_Close"
            
            if pair_col not in all_data.columns:
                raise ValueError(f"Data for {pair} not found")
            
            # Create features
            features = self._create_features(all_data, pair)
            
            # Create target (next day's return)
            target = all_data[pair_col].pct_change().shift(-1)
            
            # Drop NaN values
            valid_idx = features.notna().all(axis=1) & target.notna()
            features = features[valid_idx]
            target = target[valid_idx]
            
            if len(features) < self.min_training_samples:
                raise ValueError(f"Insufficient samples for {pair}: {len(features)}")
            
            # Time series split for training/validation
            tscv = TimeSeriesSplit(n_splits=5)
            
            # Get last split for final training
            train_idx, val_idx = list(tscv.split(features))[-1]
            
            X_train, X_val = features.iloc[train_idx], features.iloc[val_idx]
            y_train, y_val = target.iloc[train_idx], target.iloc[val_idx]
            
            # Build and train model
            model = self._build_model(input_shape=(X_train.shape[1],))
            
            # Train model
            history = model.fit(
                X_train, y_train,
                validation_data=(X_val, y_val),
                epochs=50,
                batch_size=32,
                verbose=0
            )
            
            # Evaluate model
            val_pred = model.predict(X_val)
            val_mse = mean_squared_error(y_val, val_pred)
            val_mae = mean_absolute_error(y_val, val_pred)
            
            # Save model version
            version = f"{pair}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            metrics = {
                'val_mse': val_mse,
                'val_mae': val_mae,
                'val_rmse': np.sqrt(val_mse)
            }
            params = {
                'model_type': 'LSTM',
                'layers': [64, 32],
                'epochs': 50,
                'batch_size': 32
            }
            
            model_manager.save_model_version(model, version, metrics, params, 
                                           f"Automated retraining for {pair}")
            
            return {
                'success': True,
                'version': version,
                'metrics': metrics
            }
            
        except Exception as e:
            self.logger.error(f"Error training model for {pair}: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def _create_features(self, data: pd.DataFrame, pair: str) -> pd.DataFrame:
        """Create features for model training"""
        pair_col = f"{pair.replace('/', '_')}_Close"
        
        features = pd.DataFrame(index=data.index)
        
        # Price-based features
        features['returns'] = data[pair_col].pct_change()
        features['log_returns'] = np.log(data[pair_col] / data[pair_col].shift(1))
        
        # Technical indicators
        features['sma_10'] = data[pair_col].rolling(window=10).mean()
        features['sma_30'] = data[pair_col].rolling(window=30).mean()
        features['sma_50'] = data[pair_col].rolling(window=50).mean()
        
        features['rsi'] = self._calculate_rsi(data[pair_col])
        features['macd'], features['macd_signal'] = self._calculate_macd(data[pair_col])
        
        # Volatility features
        features['volatility_10'] = features['returns'].rolling(window=10).std()
        features['volatility_30'] = features['returns'].rolling(window=30).std()
        
        # Momentum features
        features['momentum_5'] = data[pair_col] / data[pair_col].shift(5) - 1
        features['momentum_10'] = data[pair_col] / data[pair_col].shift(10) - 1
        
        # Lag features
        for lag in [1, 2, 3, 5, 10]:
            features[f'return_lag_{lag}'] = features['returns'].shift(lag)
        
        # Cross-pair features (if other pairs available)
        other_pairs = [p for p in self.config.FOREX_PAIRS if p != pair]
        for other in other_pairs[:3]:  # Use top 3 correlated pairs
            other_col = f"{other.replace('/', '_')}_Close"
            if other_col in data.columns:
                features[f'{other}_returns'] = data[other_col].pct_change()
        
        return features
    
    def _calculate_rsi(self, prices: pd.Series, window: int = 14) -> pd.Series:
        """Calculate Relative Strength Index"""
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=window).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=window).mean()
        
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        
        return rsi
    
    def _calculate_macd(self, prices: pd.Series) -> tuple:
        """Calculate MACD and signal line"""
        ema_12 = prices.ewm(span=12, adjust=False).mean()
        ema_26 = prices.ewm(span=26, adjust=False).mean()
        
        macd = ema_12 - ema_26
        signal = macd.ewm(span=9, adjust=False).mean()
        
        return macd, signal
    
    def _build_model(self, input_shape: tuple) -> keras.Model:
        """Build LSTM model for time series prediction"""
        model = keras.Sequential([
            keras.layers.LSTM(64, return_sequences=True, input_shape=input_shape),
            keras.layers.Dropout(0.2),
            keras.layers.LSTM(32),
            keras.layers.Dropout(0.2),
            keras.layers.Dense(16, activation='relu'),
            keras.layers.Dense(1)
        ])
        
        model.compile(optimizer='adam', loss='mse', metrics=['mae'])
        
        return model
    
    def _evaluate_and_deploy_models(self, model_results: Dict):
        """Evaluate models and deploy best performers"""
        successful_models = {k: v for k, v in model_results.items() if v['success']}
        
        if not successful_models:
            self.logger.error("No models trained successfully")
            return
        
        # Compare with current production models
        current_models = self._get_current_production_models()
        
        for pair, result in successful_models.items():
            new_version = result['version']
            new_metrics = result['metrics']
            
            if pair in current_models:
                current_version = current_models[pair]['version']
                current_metrics = current_models[pair]['metrics']
                
                # Compare performance
                if self._is_better_performance(new_metrics, current_metrics):
                    self.logger.info(f"Deploying new model for {pair}: {new_version} (replaces {current_version})")
                    self._deploy_model(pair, new_version)
                else:
                    self.logger.info(f"Keeping current model for {pair}: {current_version}")
            else:
                self.logger.info(f"Deploying new model for {pair}: {new_version}")
                self._deploy_model(pair, new_version)
    
    def _get_current_production_models(self) -> Dict:
        """Get currently deployed production models"""
        # This would typically check a model registry or database
        # For now, we'll use a simple file-based approach
        prod_file = os.path.join(self.config.MODEL_DIR, 'production_models.json')
        
        if os.path.exists(prod_file):
            with open(prod_file, 'r') as f:
                return json.load(f)
        else:
            return {}
    
    def _deploy_model(self, pair: str, version: str):
        """Deploy a model to production"""
        # Update production model registry
        prod_file = os.path.join(self.config.MODEL_DIR, 'production_models.json')
        
        # Load current production models
        if os.path.exists(prod_file):
            with open(prod_file, 'r') as f:
                prod_models = json.load(f)
        else:
            prod_models = {}
        
        # Update with new model
        prod_models[pair] = {
            'version': version,
            'deployed_at': datetime.now().isoformat()
        }
        
        # Save updated registry
        with open(prod_file, 'w') as f:
            json.dump(prod_models, f, indent=2)
        
        self.logger.info(f"Model {version} deployed for {pair}")
    
    def _is_better_performance(self, new_metrics: Dict, current_metrics: Dict) -> bool:
        """Check if new model performs better than current"""
        # Use validation MSE as primary metric
        new_mse = new_metrics.get('val_mse', float('inf'))
        current_mse = current_metrics.get('val_mse', float('inf'))
        
        # Consider better if MSE is at least 5% lower
        if new_mse < current_mse * 0.95:
            return True
        
        # Also consider MAE
        new_mae = new_metrics.get('val_mae', float('inf'))
        current_mae = current_metrics.get('val_mae', float('inf'))
        
        if new_mae < current_mae * 0.95:
            return True
        
        return False

# Singleton instance
retraining_system = AutomatedRetrainingSystem()