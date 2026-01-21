from typing import List, Dict
import math


def calculate_growth(current_peers: int, previous_samples: List[Dict]) -> float:
    if not previous_samples or len(previous_samples) < 2:
        return 0.0
    
    # Get the most recent previous sample
    prev_peers = previous_samples[0].get("total_peers", 0)
    
    if prev_peers == 0:
        if current_peers > 0:
            return 100.0  # 100% growth from zero
        return 0.0
    
    growth = ((current_peers - prev_peers) / prev_peers) * 100.0
    return round(growth, 2)


def calculate_shrink(current_peers: int, previous_samples: List[Dict]) -> float:
    growth = calculate_growth(current_peers, previous_samples)
    return max(0.0, -growth)  # Only return positive shrink values


def calculate_exploding_estimator(current_peers: int, previous_samples: List[Dict], 
                                  time_window_hours: float = 24.0) -> float:
    if not previous_samples or len(previous_samples) < 3:
        return 0.0
    
    # Get samples within time window (assuming timestamps are unix timestamps)
    from datetime import datetime, timezone
    current_time = datetime.now(timezone.utc).timestamp()
    window_start = current_time - (time_window_hours * 3600)
    
    recent_samples = [
        s for s in previous_samples 
        if s.get("timestamp", 0) >= window_start
    ]
    
    if len(recent_samples) < 2:
        return 0.0
    
    # Calculate growth rates for recent samples
    growth_rates = []
    for i in range(len(recent_samples) - 1):
        prev = recent_samples[i + 1].get("total_peers", 0)
        curr = recent_samples[i].get("total_peers", 0)
        if prev > 0:
            rate = ((curr - prev) / prev) * 100.0
            growth_rates.append(rate)
    
    if not growth_rates:
        return 0.0
    
    # Calculate average growth rate
    avg_growth = sum(growth_rates) / len(growth_rates)
    
    # Calculate acceleration (change in growth rate)
    if len(growth_rates) >= 2:
        acceleration = growth_rates[0] - growth_rates[-1]
    else:
        acceleration = 0.0
    
    # Calculate exploding score
    # Base score from growth rate (capped at 50 points)
    growth_score = min(50.0, max(0.0, avg_growth))
    
    # Acceleration bonus (capped at 30 points)
    accel_score = min(30.0, max(0.0, acceleration))
    
    # Sample count bonus (more samples = more reliable, capped at 20 points)
    sample_bonus = min(20.0, len(recent_samples) * 2.0)
    
    # Current peer count factor (more peers = higher potential, capped at 20 points)
    peer_factor = min(20.0, math.log10(max(1, current_peers)) * 5.0)
    
    exploding_score = growth_score + accel_score + sample_bonus + peer_factor
    
    # Normalize to 0-100
    return min(100.0, max(0.0, exploding_score))


def calculate_all_metrics(current_peers: int, current_seeders: int, current_leechers: int,
                           previous_samples: List[Dict]) -> Dict:
    growth = calculate_growth(current_peers, previous_samples)
    shrink = calculate_shrink(current_peers, previous_samples)
    exploding = calculate_exploding_estimator(current_peers, previous_samples)
    
    return {
        "growth": growth,
        "shrink": shrink,
        "exploding_estimator": round(exploding, 2)
    }

