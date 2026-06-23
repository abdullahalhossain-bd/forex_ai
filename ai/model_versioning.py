"""
Model Versioning System
Handles model versioning, storage, and deployment

NOTE: TensorFlow and MLflow are OPTIONAL. The system works without them.
"""
import os
import json
import logging
import pickle
from datetime import datetime
from typing import Dict, List, Optional, Any

# Optional ML dependencies
try:
    import tensorflow as tf
    from tensorflow import keras
    TF_AVAILABLE = True
except ImportError:
    TF_AVAILABLE = False

try:
    import mlflow
    import mlflow.tensorflow
    MLFLOW_AVAILABLE = True
except ImportError:
    MLFLOW_AVAILABLE = False

from config import Config

class ModelVersionManager:
    """Manages model versions, storage, and deployment"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.config = Config()
        self.model_dir = os.path.join(self.config.MODEL_DIR, 'versions')
        os.makedirs(self.model_dir, exist_ok=True)
        
        # Initialize MLflow — guarded so the module loads even when mlflow
        # is not installed. (Previously this ran unconditionally and broke
        # the module-level singleton `model_manager = ModelVersionManager()`.)
        if MLFLOW_AVAILABLE:
            try:
                mlflow.set_tracking_uri(f"file://{os.path.join(self.config.MODEL_DIR, 'mlruns')}")
                mlflow.tensorflow.autolog()
            except Exception as e:
                self.logger.warning("MLflow init failed (continuing without): %s", e)
        else:
            self.logger.info("MLflow not installed — model_versioning running in degraded mode.")
    
    def save_model_version(self, model: Any, version: str, metrics: Dict, 
                          params: Dict, notes: str = "") -> str:
        """Save a model version with metadata"""
        try:
            # Create version directory
            version_dir = os.path.join(self.model_dir, version)
            os.makedirs(version_dir, exist_ok=True)
            
            # Save model
            if isinstance(model, keras.Model):
                model_path = os.path.join(version_dir, 'model.keras')
                model.save(model_path)
            elif isinstance(model, tf.keras.Model):
                model_path = os.path.join(version_dir, 'model.h5')
                model.save(model_path)
            else:
                # For sklearn models
                model_path = os.path.join(version_dir, 'model.pkl')
                with open(model_path, 'wb') as f:
                    pickle.dump(model, f)
            
            # Save metadata
            metadata = {
                'version': version,
                'created_at': datetime.now().isoformat(),
                'metrics': metrics,
                'params': params,
                'notes': notes,
                'model_type': type(model).__name__,
                'model_path': model_path
            }
            
            metadata_path = os.path.join(version_dir, 'metadata.json')
            with open(metadata_path, 'w') as f:
                json.dump(metadata, f, indent=2)
            
            # Log to MLflow
            with mlflow.start_run(run_name=version):
                mlflow.log_params(params)
                mlflow.log_metrics(metrics)
                mlflow.log_artifact(metadata_path)
            
            self.logger.info(f"Model version {version} saved successfully")
            return version
            
        except Exception as e:
            self.logger.error(f"Error saving model version {version}: {e}")
            raise
    
    def load_model_version(self, version: str) -> tuple:
        """Load a model version with metadata"""
        try:
            version_dir = os.path.join(self.model_dir, version)
            
            if not os.path.exists(version_dir):
                raise ValueError(f"Model version {version} not found")
            
            # Load metadata
            metadata_path = os.path.join(version_dir, 'metadata.json')
            with open(metadata_path, 'r') as f:
                metadata = json.load(f)
            
            # Load model
            model_path = metadata['model_path']
            
            if model_path.endswith('.keras'):
                model = keras.models.load_model(model_path)
            elif model_path.endswith('.h5'):
                model = tf.keras.models.load_model(model_path)
            elif model_path.endswith('.pkl'):
                with open(model_path, 'rb') as f:
                    model = pickle.load(f)
            else:
                raise ValueError(f"Unknown model format: {model_path}")
            
            self.logger.info(f"Model version {version} loaded successfully")
            return model, metadata
            
        except Exception as e:
            self.logger.error(f"Error loading model version {version}: {e}")
            raise
    
    def list_model_versions(self) -> List[Dict]:
        """List all available model versions"""
        versions = []
        
        if not os.path.exists(self.model_dir):
            return versions
        
        for version in os.listdir(self.model_dir):
            version_dir = os.path.join(self.model_dir, version)
            if os.path.isdir(version_dir):
                metadata_path = os.path.join(version_dir, 'metadata.json')
                if os.path.exists(metadata_path):
                    try:
                        with open(metadata_path, 'r') as f:
                            metadata = json.load(f)
                        versions.append(metadata)
                    except Exception as e:
                        self.logger.error(f"Error reading metadata for {version}: {e}")
        
        # Sort by creation date
        versions.sort(key=lambda x: x['created_at'], reverse=True)
        return versions
    
    def get_latest_model_version(self) -> Optional[Dict]:
        """Get the latest model version"""
        versions = self.list_model_versions()
        return versions[0] if versions else None
    
    def compare_model_versions(self, version1: str, version2: str) -> Dict:
        """Compare two model versions"""
        try:
            _, metadata1 = self.load_model_version(version1)
            _, metadata2 = self.load_model_version(version2)
            
            comparison = {
                'version1': version1,
                'version2': version2,
                'metrics_comparison': {},
                'params_comparison': {},
                'performance_diff': {}
            }
            
            # Compare metrics
            all_metrics = set(metadata1['metrics'].keys()) | set(metadata2['metrics'].keys())
            for metric in all_metrics:
                val1 = metadata1['metrics'].get(metric, None)
                val2 = metadata2['metrics'].get(metric, None)
                
                if val1 is not None and val2 is not None:
                    diff = val2 - val1
                    pct_change = ((val2 - val1) / val1) * 100 if val1 != 0 else 0
                    
                    comparison['metrics_comparison'][metric] = {
                        'version1': val1,
                        'version2': val2,
                        'difference': diff,
                        'percent_change': pct_change
                    }
            
            # Compare parameters
            all_params = set(metadata1['params'].keys()) | set(metadata2['params'].keys())
            for param in all_params:
                val1 = metadata1['params'].get(param, None)
                val2 = metadata2['params'].get(param, None)
                
                comparison['params_comparison'][param] = {
                    'version1': val1,
                    'version2': val2
                }
            
            return comparison
            
        except Exception as e:
            self.logger.error(f"Error comparing model versions: {e}")
            raise
    
    def delete_model_version(self, version: str) -> bool:
        """Delete a model version"""
        try:
            version_dir = os.path.join(self.model_dir, version)
            
            if not os.path.exists(version_dir):
                self.logger.warning(f"Model version {version} not found")
                return False
            
            # Delete directory and all contents
            import shutil
            shutil.rmtree(version_dir)
            
            self.logger.info(f"Model version {version} deleted successfully")
            return True
            
        except Exception as e:
            self.logger.error(f"Error deleting model version {version}: {e}")
            return False

# Singleton instance
model_manager = ModelVersionManager()