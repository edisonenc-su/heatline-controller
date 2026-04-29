
def should_emit_transition(previous_state: str, next_state: str) -> bool:
    return previous_state != next_state and next_state in {'detected', 'clear'}


def build_transition_event(next_state: str):
    if next_state == 'detected':
        return {
            'event_type': 'snow_detected',
            'severity': 'info',
            'message': '강설 감지 상태로 전환되었습니다.'
        }
    return {
        'event_type': 'snow_cleared',
        'severity': 'info',
        'message': '강설 감지가 해제되었습니다.'
    }
