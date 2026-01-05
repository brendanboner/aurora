#!/usr/bin/env python3
"""
CLI tool for A/B testing different LLM temperatures with CreatorAgents.

Usage:
    python -m content_creator_service.src.scripts.test_temperatures \
        --agent-id 1 \
        --temperatures 0.7,0.8,0.9 \
        --runs-per-temp 3

This generates posts at different temperatures and saves results for comparison.
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import List

# Add parent directory to path to allow imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Load .env file if present
from dotenv import load_dotenv
env_path = Path(__file__).parent.parent.parent.parent / ".env"
if env_path.exists():
    load_dotenv(env_path)

# Override service hostnames to use localhost when running from CLI (after loading .env)
os.environ["POSTGRES_HOST"] = "localhost"
# Override PG_DSN if it contains docker hostnames
if "PG_DSN" in os.environ:
    pg_dsn = os.environ["PG_DSN"]
    pg_dsn = pg_dsn.replace("@aurora-postgres:", "@localhost:")
    pg_dsn = pg_dsn.replace("@postgres:", "@localhost:")
    os.environ["PG_DSN"] = pg_dsn

if "neo4j:7687" in os.environ.get("NEO4J_URI", ""):
    os.environ["NEO4J_URI"] = "bolt://localhost:7687"
if os.environ.get("RABBITMQ_HOST") == "rabbitmq":
    os.environ["RABBITMQ_HOST"] = "localhost"

from src import db
from src.services.agent_service import AgentService
from src.services.generation_service import GenerationService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="A/B test different LLM temperatures for post generation"
    )
    parser.add_argument(
        "--agent-id",
        type=int,
        required=True,
        help="ID of the CreatorAgent to test"
    )
    parser.add_argument(
        "--temperatures",
        type=str,
        default="0.7,0.8,0.9",
        help="Comma-separated list of temperatures to test (default: 0.7,0.8,0.9)"
    )
    parser.add_argument(
        "--runs-per-temp",
        type=int,
        default=3,
        help="Number of generations per temperature (default: 3)"
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="./test_results",
        help="Directory to save test results (default: ./test_results)"
    )
    
    return parser.parse_args()


def test_temperature(
    agent_service: AgentService,
    generation_service: GenerationService,
    agent_id: int,
    temperature: float,
    run_number: int,
) -> dict:
    """Generate a single post at given temperature."""
    logger.info(f"Generating post for agent {agent_id} at temp={temperature} (run {run_number})")
    
    # Get agent
    agent = agent_service.get_agent(agent_id)
    
    # Override temperature temporarily
    original_temp = agent.llm_temperature_override
    agent.llm_temperature_override = temperature
    
    try:
        # Generate post
        payload = generation_service.generate_post_payload(agent)
        
        if not payload:
            logger.warning("No content generated")
            return {
                "status": "failed",
                "error": "No content generated"
            }
        
        return {
            "status": "success",
            "temperature": temperature,
            "run": run_number,
            "title": payload.get("title"),
            "body": payload.get("body"),
            "summary": payload.get("summary"),
            "tags": payload.get("tags"),
            "word_count": len(payload.get("body", "").split()),
            "char_count": len(payload.get("body", "")),
        }
    except Exception as e:
        logger.error(f"Generation failed: {e}")
        return {
            "status": "failed",
            "error": str(e)
        }
    finally:
        # Restore original temperature
        agent.llm_temperature_override = original_temp


def main() -> int:
    args = parse_args()
    
    # Parse temperatures
    try:
        temperatures = [float(t.strip()) for t in args.temperatures.split(",")]
    except ValueError:
        logger.error("Invalid temperature format. Use comma-separated floats (e.g., 0.7,0.8,0.9)")
        return 1
    
    # Validate temperatures
    for temp in temperatures:
        if not (0.0 <= temp <= 1.0):
            logger.error(f"Temperature {temp} out of range [0.0, 1.0]")
            return 1
    
    # Create output directory
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Initialize services
    db.init_pool()
    agent_service = AgentService()
    generation_service = GenerationService()
    
    try:
        # Verify agent exists
        agent = agent_service.get_agent(args.agent_id)
        logger.info(f"Testing agent: {agent.name} (ID: {agent.id})")
        logger.info(f"Temperatures: {temperatures}")
        logger.info(f"Runs per temperature: {args.runs_per_temp}")
        
        # Run tests
        all_results = []
        
        for temp in temperatures:
            logger.info(f"\n{'=' * 60}")
            logger.info(f"Testing temperature: {temp}")
            logger.info(f"{'=' * 60}\n")
            
            for run in range(1, args.runs_per_temp + 1):
                result = test_temperature(
                    agent_service,
                    generation_service,
                    args.agent_id,
                    temp,
                    run
                )
                all_results.append(result)
        
        # Save results
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = output_dir / f"temperature_test_{agent.name}_{timestamp}.json"
        
        test_summary = {
            "agent": {
                "id": agent.id,
                "name": agent.name,
                "tone_style": agent.tone_style,
                "original_temperature": agent.llm_temperature_override,
            },
            "test_config": {
                "temperatures": temperatures,
                "runs_per_temp": args.runs_per_temp,
                "timestamp": timestamp,
            },
            "results": all_results,
        }
        
        with open(output_file, "w") as f:
            json.dump(test_summary, f, indent=2, default=str)
        
        logger.info(f"\n{'=' * 60}")
        logger.info(f"Test complete! Results saved to:")
        logger.info(f"  {output_file}")
        logger.info(f"{'=' * 60}\n")
        
        # Print summary statistics
        successful = [r for r in all_results if r["status"] == "success"]
        failed = [r for r in all_results if r["status"] == "failed"]
        
        logger.info(f"Summary:")
        logger.info(f"  Total runs: {len(all_results)}")
        logger.info(f"  Successful: {len(successful)}")
        logger.info(f"  Failed: {len(failed)}")
        
        if successful:
            for temp in temperatures:
                temp_results = [r for r in successful if r.get("temperature") == temp]
                if temp_results:
                    avg_words = sum(r.get("word_count", 0) for r in temp_results) / len(temp_results)
                    logger.info(f"\n  Temperature {temp}:")
                    logger.info(f"    Runs: {len(temp_results)}")
                    logger.info(f"    Avg word count: {avg_words:.0f}")
        
        return 0
        
    except Exception as e:
        logger.error(f"Test failed: {e}")
        return 1
    finally:
        db.close_pool()


if __name__ == "__main__":
    sys.exit(main())
