from collections import deque


class DecisionSmoother:
    def __init__(self, positive_threshold, negative_threshold, positive_streak, negative_streak):
        self.positive_threshold = positive_threshold
        self.negative_threshold = negative_threshold
        self.positive_streak = positive_streak
        self.negative_streak = negative_streak
        self.window = deque(maxlen=max(positive_streak, negative_streak, 10))
        self.state = 'unknown'

    def update(self, score: float):
        self.window.append(score)
        recent = list(self.window)
        if len(recent) >= self.positive_streak and all(v >= self.positive_threshold for v in recent[-self.positive_streak:]):
            self.state = 'detected'
        elif len(recent) >= self.negative_streak and all(v <= self.negative_threshold for v in recent[-self.negative_streak:]):
            self.state = 'clear'
        else:
            self.state = 'uncertain'
        avg = sum(recent) / len(recent)
        return {
            'snow_detected': self.state == 'detected',
            'snow_state': self.state,
            'snow_confidence': round(avg, 4)
        }
