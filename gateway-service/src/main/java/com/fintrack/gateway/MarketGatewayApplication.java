package com.fintrack.gateway;

import com.fintrack.gateway.config.GatewayProperties;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.EnableConfigurationProperties;

@SpringBootApplication
@EnableConfigurationProperties(GatewayProperties.class)
public class MarketGatewayApplication {
    public static void main(String[] args) {
        SpringApplication.run(MarketGatewayApplication.class, args);
    }
}
