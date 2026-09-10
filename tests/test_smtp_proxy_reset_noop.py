from proxy_manager import reset_smtplib_proxy, smtp_global_proxy_is_active


def test_reset_is_noop_when_inactive():
    reset_smtplib_proxy()
    assert smtp_global_proxy_is_active() is False
    # second call must stay quiet/no-op
    reset_smtplib_proxy()
    assert smtp_global_proxy_is_active() is False
