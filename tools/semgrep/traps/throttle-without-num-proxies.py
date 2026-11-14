def behind_proxy_unknown():
    # ruleid: throttle-without-num-proxies
    REST_FRAMEWORK = {
        "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.UserRateThrottle"],
        "DEFAULT_THROTTLE_RATES": {"user": "200/min"},
    }
    return REST_FRAMEWORK


def behind_one_proxy():
    # ok: throttle-without-num-proxies
    REST_FRAMEWORK = {
        "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.UserRateThrottle"],
        "DEFAULT_THROTTLE_RATES": {"user": "200/min"},
        "NUM_PROXIES": 1,
    }
    return REST_FRAMEWORK


def no_throttling():
    # ok: throttle-without-num-proxies
    REST_FRAMEWORK = {"PAGE_SIZE": 50}
    return REST_FRAMEWORK
