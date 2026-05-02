# 🤖 Binance Futures Trading Bot - EMA/RSI/ATR Strategy

Este es un bot de trading automático para **Binance Futures** (BTCUSDT por defecto) que utiliza una combinación de medias móviles exponenciales (EMA), el índice de fuerza relativa (RSI) y el rango verdadero promedio (ATR) para la gestión de riesgo.

## 📊 Estrategia de Trading

El bot opera bajo una estrategia tendencial (Trend Following) muy robusta, aplicando múltiples filtros para evitar mercados laterales y operando con medidas anti-repainting (usando únicamente velas confirmadas por cierre):

1.  **Directriz Principal (EMA 200)**: No se abre ninguna operación que vaya en contra del macro-movimiento.
    *   Solo se permiten compras (**LONG**) si el precio de cierre está **por encima** de la EMA de 200.
    *   Solo se permiten ventas (**SHORT**) si el precio de cierre está **por debajo** de la EMA de 200.
2.  **Gatillo de Entrada (EMAs 9 y 21)**: Determina el instante exacto de nuestro giro en temporalidad local.
    *   **LONG**: Cuando la EMA rápida (9) cruza limpiamente hacia arriba la EMA lenta (21).
    *   **SHORT**: Cuando la EMA rápida (9) cruza limpiamente hacia abajo la EMA lenta (21).
3.  **Fuerza Adicional (ADX 14)**:
    *   Filtro estricto que exige un valor de **ADX > 20** para asegurar que el mercado lleva direccionalidad, evitando así descapitalizarse en zonas de acumulación (falsos cruces por precio lateral / choppiness).
4.  **Filtro Momentum (RSI 14)**: Evita compras en el final del recorrido (pico superior) o ventas en el suelo.
    *   Para **LONG**: RSI < 70 (debe haber margen de subida sin estar sobrecomprado).
    *   Para **SHORT**: RSI > 30 (debe haber margen de caída sin estar sobrevendido).
5.  **Gestión Dinámica de Riesgo (ATR 14)**:
    *   **Stop Loss (SL)**: A una distancia de 1.5 × ATR desde el precio de entrada, adaptándose pasivamente a la volatilidad del mercado en ese momento.
    *   **Take Profit (TP)**: A una distancia de 3.0 × ATR, persiguiendo un ratio Riesgo/Beneficio ideal asimétrico de 1:2.
    *   **Riesgo estricto por trade**: Arriesga topado en pérdida exactamente el 2% de tu balance disponible computando automáticamente la cantidad a comprar/vender.
    *   **Apalancamiento base**: 3x como configuración estándar para el bot.

## 🚀 Requisitos Previos

*   Cuenta en Binance con Futuros habilitados.
*   API Key y API Secret de Binance (preferiblemente de Testnet para pruebas iniciales).
*   Bot de Telegram (opcional, para notificaciones).
*   Docker y Docker Compose instalados (recomendado).

## 🛠️ Configuración

1.  Clona este repositorio o copia los archivos.
2.  Crea un archivo `.env` basado en el `env.example`:
    ```bash
    cp env.example .env
    ```
3.  Completa tus credenciales en el archivo `.env`:
    *   `BINANCE_API_KEY`: Tu clave API.
    *   `BINANCE_API_SECRET`: Tu clave secreta.
    *   `TELEGRAM_BOT_TOKEN`: El token proporcionado por [@BotFather](https://t.me/BotFather).
    *   `TELEGRAM_CHAT_ID`: Tu ID de chat (puedes obtenerlo de [@userinfobot](https://t.me/userinfobot)).

## 🐳 Ejecución con Docker (Recomendado)

El bot está preparado para correr en un contenedor Docker de forma ininterrumpida.

```bash
docker-compose up -d --build
```

Esto levantará el bot en segundo plano y guardará los logs en la carpeta `./logs`.

## 🐍 Ejecución Local (Python)

Si prefieres correrlo directamente con Python:

1.  Instala las dependencias:
    ```bash
    pip install -r requirements.txt
    ```
2.  Ejecuta el bot:
    ```bash
    python binance_bot.py
    ```

## ⚙️ Parámetros del Bot

Puedes ajustar el comportamiento del bot modificando el diccionario `CONFIG` en `binance_bot.py`:

*   `symbol`: Par a tradear (Ej: "BTCUSDT").
*   `interval`: Temporalidad de las velas (Ej: "15m").
*   `leverage`: Apalancamiento (Ej: 3).
*   `risk_pct`: Porcentaje de balance a arriesgar por trade (Ej: 0.02 para 2%).
*   `testnet`: `True` para usar Binance Testnet, `False` para dinero real.

## 📱 Notificaciones de Telegram

El bot envía mensajes automáticos cuando:
*   Se inicia el script.
*   Se abre una nueva orden (con detalles de SL, TP y Riesgo).
*   Se cierra una posición (con el PnL obtenido).
*   Ocurre un error.
*   Resumen horario (Heartbeat) con el estado actual del mercado y la cuenta.

---

### ⚠️ Descargo de Responsabilidad
Este software es solo para fines educativos. El trading de futuros implica un riesgo significativo de pérdida. Los autores no se hacen responsables de las pérdidas financieras incurridas por el uso de este bot. **Prueba siempre en Testnet antes de usar dinero real.**
