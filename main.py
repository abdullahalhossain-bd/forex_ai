"""
Main Entry Point for Forex AI Trading System
Integrates all components and manages system lifecycle
"""
import os
import sys
import logging
import argparse
from datetime import datetime
from typing import Optional

# Add project root to path
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

from config import Config
from data.automated_updater import data_updater
from ai.automated_retraining import retraining_system
from risk.portfolio_manager import portfolio_manager
from core.monitoring_system import monitoring_system

class ForexAITradingSystem:
    """Main Forex AI Trading System orchestrator"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.config = Config()
        
        # Initialize all components
        self.data_updater = data_updater
        self.retraining_system = retraining_system
        self.portfolio_manager = portfolio_manager
        self.monitoring_system = monitoring_system
        
        # System state
        self.running = False
        self.start_time = None
        
    def initialize(self):
        """Initialize all system components"""
        self.logger.info("Initializing Forex AI Trading System")
        
        try:
            # Initialize data pipeline
            self.logger.info("Initializing data pipeline...")
            data_status = self.data_updater.update_all_pairs()
            if not all(data_status.values()):
                self.logger.warning("Some currency pairs failed to update - system may have limited functionality")
            
            # Initialize AI models
            self.logger.info("Initializing AI models...")
            model_status = self.retraining_system._get_current_production_models()
            if not model_status:
                self.logger.warning("No production models available - training new models")
                self.retraining_system._retrain_models()
            
            # Initialize monitoring
            self.logger.info("Starting monitoring system...")
            self.monitoring_system.start_monitoring()
            
            # Start automated retraining schedule
            self.logger.info("Starting automated model retraining...")
            self.retraining_system.start_scheduled_retraining()
            
            self.logger.info("System initialization completed successfully")
            return True
            
        except Exception as e:
            self.logger.error(f"Error during system initialization: {e}")
            return False
    
    def start_trading(self):
        """Start the trading system"""
        if self.running:
            self.logger.warning("Trading system is already running")
            return
        
        self.logger.info("Starting Forex AI Trading System")
        
        try:
            self.running = True
            self.start_time = datetime.now()
            
            # Main trading loop would go here
            # For now, just keep the system running
            while self.running:
                try:
                    # Update portfolio
                    # self._update_portfolio()
                    
                    # Generate signals
                    # signals = self._generate_signals()
                    
                    # Execute trades
                    # self._execute_trades(signals)
                    
                    # Check risk limits
                    risk_status = self.portfolio_manager.check_risk_limits()
                    
                    if risk_status['status'] == 'limit_exceeded':
                        self.logger.warning(f"Risk limits exceeded: {risk_status}")
                        # Implement risk reduction logic
                    
                    # Sleep until next iteration
                    import time
                    time.sleep(60)  # 1 minute interval
                    
                except KeyboardInterrupt:
                    self.logger.info("Received keyboard interrupt - shutting down")
                    self.stop_trading()
                    break
                    
                except Exception as e:
                    self.logger.error(f"Error in main trading loop: {e}")
                    time.sleep(60)  # Wait before retrying
                    
        except Exception as e:
            self.logger.error(f"Error starting trading system: {e}")
            self.running = False
    
    def stop_trading(self):
        """Stop the trading system"""
        self.logger.info("Stopping Forex AI Trading System")
        
        self.running = False
        
        # Save final state
        self._save_system_state()
        
        self.logger.info("Trading system stopped")
    
    def _save_system_state(self):
        """Save current system state"""
        try:
            state = {
                'timestamp': datetime.now().isoformat(),
                'uptime': str(datetime.now() - self.start_time) if self.start_time else None,
                'portfolio_value': self.portfolio_manager.portfolio_value,
                'positions': self.portfolio_manager.positions,
                'system_status': self.monitoring_system.get_system_status()
            }
            
            state_file = os.path.join(self.config.DATA_DIR, 'system_state.json')
            
            with open(state_file, 'w') as f:
                import json
                json.dump(state, f, indent=2, default=str)
            
            self.logger.info(f"System state saved to {state_file}")
            
        except Exception as e:
            self.logger.error(f"Error saving system state: {e}")
    
    def get_system_status(self) -> dict:
        """Get comprehensive system status"""
        try:
            status = {
                'running': self.running,
                'uptime': str(datetime.now() - self.start_time) if self.start_time and self.running else None,
                'timestamp': datetime.now().isoformat(),
                'components': {
                    'data_pipeline': self._get_data_pipeline_status(),
                    'ai_models': self._get_ai_models_status(),
                    'trading_system': self._get_trading_system_status(),
                    'monitoring': self.monitoring_system.get_system_status()
                }
            }
            
            return status
            
        except Exception as e:
            self.logger.error(f"Error getting system status: {e}")
            return {'error': str(e)}
    
    def _get_data_pipeline_status(self) -> dict:
        """Get data pipeline status"""
        try:
            status = self.data_updater.get_data_status()
            
            total_pairs = len(status)
            ok_pairs = sum(1 for s in status.values() if s.get('status') == 'OK')
            
            return {
                'status': 'ok' if ok_pairs == total_pairs else 'warning',
                'total_pairs': total_pairs,
                'ok_pairs': ok_pairs,
                'pairs': status
            }
        except Exception as e:
            return {'status': 'error', 'message': str(e)}
    
    def _get_ai_models_status(self) -> dict:
        """Get AI models status"""
        try:
            from ai.model_versioning import model_manager
            
            versions = model_manager.list_model_versions()
            latest = model_manager.get_latest_model_version()
            
            return {
                'status': 'ok' if latest else 'warning',
                'total_versions': len(versions),
                'latest_version': latest,
                'production_models': self.retraining_system._get_current_production_models()
            }
        except Exception as e:
            return {'status': 'error', 'message': str(e)}
    
    def _get_trading_system_status(self) -> dict:
        """Get trading system status"""
        try:
            return {
                'status': 'ok' if self.running else 'stopped',
                'portfolio_value': self.portfolio_manager.portfolio_value,
                'open_positions': len(self.portfolio_manager.positions),
                'risk_status': self.portfolio_manager.check_risk_limits()
            }
        except Exception as e:
            return {'status': 'error', 'message': str(e)}

def setup_logging():
    """Configure comprehensive logging"""
    log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    log_level = logging.INFO
    
    # Create logs directory
    log_dir = os.path.join(os.path.dirname(__file__), 'logs')
    os.makedirs(log_dir, exist_ok=True)
    
    # Configure logging
    logging.basicConfig(
        level=log_level,
        format=log_format,
        handlers=[
            logging.FileHandler(os.path.join(log_dir, 'forex_ai.log')),
            logging.StreamHandler()
        ]
    )
    
    # Reduce verbosity of some libraries
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('matplotlib').setLevel(logging.WARNING)

def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description='Forex AI Trading System')
    parser.add_argument('--mode', choices=['init', 'start', 'status', 'stop'], 
                       default='start', help='System mode')
    parser.add_argument('--config', help='Configuration file path')
    
    args = parser.parse_args()
    
    # Setup logging
    setup_logging()
    
    logger = logging.getLogger(__name__)
    logger.info("Forex AI Trading System - Starting")
    
    try:
        # Initialize system
        system = ForexAITradingSystem()
        
        if args.mode == 'init':
            # Initialize system only
            success = system.initialize()
            if success:
                logger.info("System initialized successfully")
                sys.exit(0)
            else:
                logger.error("System initialization failed")
                sys.exit(1)
                
        elif args.mode == 'start':
            # Start full system
            if system.initialize():
                system.start_trading()
            else:
                logger.error("System initialization failed")
                sys.exit(1)
                
        elif args.mode == 'status':
            # Get system status
            status = system.get_system_status()
            import json
            print(json.dumps(status, indent=2, default=str))
            
        elif args.mode == 'stop':
            # Stop system (if running)
            logger.info("Stop command received - system would be stopped if running")
            
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()