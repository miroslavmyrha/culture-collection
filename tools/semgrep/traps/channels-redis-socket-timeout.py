import os

redis_url = os.environ["REDIS_URL"]

CHANNEL_LAYERS = {
    # ruleid: channels-redis-socket-timeout
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {"hosts": [redis_url]},
    },
    # ok: channels-redis-socket-timeout
    "fixed": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {"hosts": [{"address": redis_url, "socket_timeout": None}]},
    },
    # ok: channels-redis-socket-timeout
    "tests": {"BACKEND": "channels.layers.InMemoryChannelLayer"},
}
