package com.fintrack.gateway;

import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;

@SpringBootTest(properties = "fintrack.gateway.upstream-base-url=http://127.0.0.1:65530")
class MarketGatewayApplicationTests {
    @Test
    void contextLoads() { }
}
