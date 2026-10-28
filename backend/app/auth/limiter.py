import hashlib
import hmac
from typing import cast

from redis import Redis
from redis.exceptions import RedisError

# One atomic fixed window per source IP and normalized company/email identity.
_SCRIPT = """
local blocked = 0
for i, key in ipairs(KEYS) do
  local count = redis.call('INCR', key)
  if count == 1 then redis.call('EXPIRE', key, 60) end
  if count > tonumber(ARGV[i]) then blocked = 1 end
end
return blocked
"""


class LimiterUnavailable(Exception):
    pass


class RedisLoginLimiter:
    def __init__(
        self, client: Redis, secret: str, prefix: str = "portal:login"
    ) -> None:
        self.client = client
        self.secret = secret.encode()
        self.prefix = prefix

    def allow(self, ip: str, identity: str) -> bool:
        def key(kind: str, value: str) -> str:
            digest = hmac.new(self.secret, value.encode(), hashlib.sha256).hexdigest()
            return f"{self.prefix}:{kind}:{digest}"

        try:
            blocked = cast(
                int,
                self.client.eval(
                    _SCRIPT, 2, key("ip", ip), key("identity", identity), "30", "10"
                ),
            )
        except RedisError:
            raise LimiterUnavailable from None
        return blocked == 0
