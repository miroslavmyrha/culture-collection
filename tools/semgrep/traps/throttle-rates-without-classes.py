def loose():
    # ruleid: throttle-rates-without-classes
    REST_FRAMEWORK = {
        "DEFAULT_THROTTLE_RATES": {"anon": "20/min", "user": "200/min"},
        "NUM_PROXIES": 1,
    }
    return REST_FRAMEWORK


def scoped_only():
    # ok: throttle-rates-without-classes
    REST_FRAMEWORK = {
        "DEFAULT_THROTTLE_RATES": {"login": "5/min"},
        "NUM_PROXIES": 1,
    }
    return REST_FRAMEWORK


def strict():
    # ok: throttle-rates-without-classes
    REST_FRAMEWORK = {
        "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.AnonRateThrottle"],
        "DEFAULT_THROTTLE_RATES": {"anon": "20/min"},
        "NUM_PROXIES": 1,
    }
    return REST_FRAMEWORK
