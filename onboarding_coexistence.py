import os

META_APP_ID = os.getenv("META_APP_ID", "TU_APP_ID_AQUI")
GRAPH_VERSION = os.getenv("GRAPH_VERSION", "v21.0")
CONFIG_ID = os.getenv("CONFIG_ID", "TU_CONFIG_ID_DE_EMBEDDED_SIGNUP")
REDIRECT_URI = os.getenv("REDIRECT_URI", "https://tu-dominio.com/callback/whatsapp")
EVOLUTION_API_URL = os.getenv("EVOLUTION_API_URL", "https://tu-evolution-api.com")
EVOLUTION_API_KEY = os.getenv("EVOLUTION_API_KEY", "TU_APIKEY")

ONBOARDING_HTML = f"""<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Conectar WhatsApp - Sisnova</title>
    <style>
        body {{ font-family: Arial, sans-serif; text-align: center; padding: 50px; background: #f0f2f5; }}
        .container {{ max-width: 500px; margin: 0 auto; background: white; padding: 40px; border-radius: 12px; box-shadow: 0 2px 12px rgba(0,0,0,0.1); }}
        h1 {{ color: #1a1a2e; margin-bottom: 16px; }}
        p {{ color: #555; line-height: 1.6; }}
        #launch-btn {{ padding: 14px 28px; font-size: 16px; background: #1877F2; color: white; border: none; border-radius: 8px; cursor: pointer; font-weight: bold; margin-top: 10px; }}
        #launch-btn:hover:not(:disabled) {{ background: #145dbf; }}
        #launch-btn:disabled {{ opacity: 0.6; cursor: not-allowed; }}
        #status {{ margin-top: 20px; padding: 12px 16px; border-radius: 8px; display: none; font-size: 14px; text-align: left; }}
        #status.success {{ background: #d4edda; color: #155724; }}
        #status.error {{ background: #f8d7da; color: #721c24; }}
        #status.loading {{ background: #d1ecf1; color: #0c5460; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Conecta tu WhatsApp Business</h1>
        <p>Hace clic en el boton de abajo para conectar tu numero de WhatsApp Business a nuestra plataforma. Se abrira una ventana de Facebook para completar el proceso.</p>

        <button id="launch-btn" onclick="launchWhatsAppSignup()">
            Conectar con WhatsApp Business
        </button>

        <div id="status"></div>
    </div>

    <!-- Facebook JS SDK (requerido por Meta Embedded Signup v4) -->
    <script async defer crossorigin="anonymous" src="https://connect.facebook.net/es_LA/sdk.js"></script>

    <script>
        // Acumular datos de ambos eventos (FB.login callback y postMessage)
        let _authCode = null;
        let _sessionData = null;

        function showStatus(msg, type) {{
            const el = document.getElementById('status');
            el.textContent = msg;
            el.className = type;
            el.style.display = 'block';
        }}

        // Paso 1: Inicializar el SDK de Facebook
        window.fbAsyncInit = function() {{
            FB.init({{
                appId: '{META_APP_ID}',
                version: '{GRAPH_VERSION}',
                xfbml: true,
                cookie: true
            }});
            console.log('Facebook SDK inicializado');
        }};

        // Paso 2: Listener postMessage — Meta envia phone_number_id, waba_id y business_id
        // cuando el usuario completa el flujo de Embedded Signup
        window.addEventListener('message', function(event) {{
            if (!event.origin.endsWith('facebook.com')) return;
            try {{
                const data = JSON.parse(event.data);
                console.log('postMessage recibido:', data);
                if (data.type === 'WA_EMBEDDED_SIGNUP') {{
                    if (data.event === 'FINISH' || data.event === 'FINISH_ONLY_WABA') {{
                        _sessionData = data.data;
                        console.log('Datos de sesion recibidos:', _sessionData);
                        tryCompleteOnboarding();
                    }} else if (data.event === 'CANCEL') {{
                        console.log('Flujo cancelado en paso:', data.data.current_step);
                        showStatus('Proceso cancelado. Podes volver a intentarlo.', 'error');
                        document.getElementById('launch-btn').disabled = false;
                    }}
                }}
            }} catch (e) {{
                console.log('mensaje raw:', event.data);
            }}
        }}, false);

        // Paso 3: Callback del FB.login — recibe el codigo de autorizacion (code, TTL 30s)
        function fbLoginCallback(response) {{
            if (response.authResponse) {{
                _authCode = response.authResponse.code;
                console.log('Codigo de autorizacion recibido');
                tryCompleteOnboarding();
            }} else {{
                console.log('Login cancelado o fallido:', response);
                showStatus('Login cancelado. Por favor, intenta de nuevo.', 'error');
                document.getElementById('launch-btn').disabled = false;
            }}
        }}

        // Paso 4: Cuando tenemos AMBOS datos (code + sessionData), enviar al backend
        // El backend hara: exchange code -> register phone -> subscribe webhooks -> create Evolution instance
        function tryCompleteOnboarding() {{
            if (!_authCode || !_sessionData) {{
                return; // esperar al otro evento
            }}
            showStatus('Configurando tu WhatsApp... por favor espera.', 'loading');
            document.getElementById('launch-btn').disabled = true;

            const payload = {{
                code: _authCode,
                phone_number_id: _sessionData.phone_number_id,
                waba_id: _sessionData.waba_id,
                business_id: _sessionData.business_id
            }};
            console.log('Enviando al backend:', {{...payload, code: '[REDACTED]'}});

            fetch('/api/onboard-whatsapp', {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json' }},
                body: JSON.stringify(payload)
            }})
            .then(resp => resp.json())
            .then(res => {{
                if (res.status === 'ok') {{
                    showStatus('Conexion exitosa! Tu WhatsApp esta siendo configurado. Ya podes cerrar esta pagina.', 'success');
                }} else {{
                    showStatus('Error: ' + (res.error || 'Ocurrio un error inesperado.'), 'error');
                    document.getElementById('launch-btn').disabled = false;
                }}
            }})
            .catch(err => {{
                console.error('Error de red:', err);
                showStatus('Error de red. Por favor, recarga la pagina e intenta de nuevo.', 'error');
                document.getElementById('launch-btn').disabled = false;
            }});
        }}

        // Paso 5: Lanzar el flujo de Embedded Signup via FB.login
        // Metodo recomendado por Meta para Embedded Signup v4
        function launchWhatsAppSignup() {{
            _authCode = null;
            _sessionData = null;
            document.getElementById('launch-btn').disabled = true;
            showStatus('Iniciando flujo de Facebook...', 'loading');

            FB.login(fbLoginCallback, {{
                config_id: '{CONFIG_ID}',
                response_type: 'code',
                override_default_response_type: true,
                extras: {{
                    setup: {{}}
                }}
            }});
        }}
    </script>
</body>
</html>
"""
