from unittest.mock import patch

from hlvault.notify.telegram import send_alert


def test_send_alert_returns_false_when_not_configured():
    assert send_alert("", "", "hello") is False


def test_send_alert_returns_true_on_success():
    with patch("hlvault.notify.telegram.resilient_read", return_value=True):
        assert send_alert("tok", "chat", "hello") is True


def test_send_alert_returns_false_and_does_not_raise_on_failure():
    with patch("hlvault.notify.telegram.resilient_read", side_effect=RuntimeError("boom")):
        assert send_alert("tok", "chat", "hello") is False


def test_send_alert_handles_non_serializable_message_without_raising():
    class NotSerializable:
        pass
    # should not raise, and should return False (json.dumps will fail internally)
    assert send_alert("tok", "chat", NotSerializable()) is False
