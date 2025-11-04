import os
import time
import requests
from typing import List, Dict

class ScenarioRunner:
    def __init__(self, base_url: str, api_key: str, agent_id: str, scenarios: List[str], 
                 frequency: int = 1, timeout: int = 3600, poll_interval: int = 30):
        self.base_url = base_url.rstrip('/')
        self.headers = {
            'X-CEKURA-API-KEY': api_key,
            'Content-Type': 'application/json'
        }
        self.agent_id = agent_id
        self.scenarios = scenarios
        self.frequency = frequency
        self.timeout = timeout
        self.poll_interval = poll_interval

    def run_scenarios(self) -> str:
        """Run scenarios and return result ID"""
        url = f"{self.base_url}/test_framework/v1/scenarios/run_scenarios/"
        payload = {
            "agent_id": self.agent_id,
            "scenarios": self.scenarios,
            "frequency": self.frequency
        }
        
        try:
            response = requests.post(url, headers=self.headers, json=payload)
            response.raise_for_status()
            result_id = response.json().get('id')
            if not result_id:
                raise Exception("No result ID returned from API")
            return result_id
        except requests.exceptions.RequestException as e:
            raise Exception(f"Error running scenarios: {e}")

    def check_result_status(self, result_id: str) -> Dict:
        """Check status of a result"""
        url = f"{self.base_url}/test_framework/v1/results/{result_id}/"
        try:
            response = requests.get(url, headers=self.headers)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            raise Exception(f"Error checking result status: {e}")

    def run_and_monitor(self):
        """Run scenarios and monitor until completion"""
        result_id = self.run_scenarios()
        print(f"Started scenarios with result ID: {result_id}")
        
        start_time = time.time()
        while True:
            if time.time() - start_time > self.timeout:
                raise Exception("Timeout reached while waiting for scenarios to complete")
                
            result = self.check_result_status(result_id)
            status = result.get('status')
            
            if not status:
                raise Exception("Error fetching result status")
                
            if status in ['completed', 'failed']:
                print(f"Scenarios finished with status: {status}")
                if status == 'failed':
                    raise Exception("Scenarios failed")
                return
                
            time.sleep(self.poll_interval)

def get_env_vars() -> Dict:
    """Get and validate all required environment variables"""
    try:
        scenarios = [s.strip() for s in os.environ['SCENARIOS'].split(',')]
        return {
            'base_url': os.environ['API_BASE_URL'],
            'api_key': os.environ['API_KEY'],
            'agent_id': os.environ['AGENT_ID'],
            'scenarios': scenarios,
            'frequency': int(os.environ.get('FREQUENCY', '1')),
            'timeout': int(os.environ.get('TIMEOUT', '3600')),
            'poll_interval': int(os.environ.get('POLL_INTERVAL', '30'))
        }
    except KeyError as e:
        raise Exception(f"Missing required environment variable: {e}")
    except ValueError as e:
        raise Exception(f"Invalid environment variable value: {e}")

def main():
    config = get_env_vars()
    runner = ScenarioRunner(**config)
    runner.run_and_monitor()

if __name__ == "__main__":
    main() 