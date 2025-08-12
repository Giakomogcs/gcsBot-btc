import subprocess
import os
import asyncio

async def run_command_in_container(command: list, env_vars: dict = {}, interactive: bool = False, ws=None):
    """
    Executa um comando Python dentro do container 'app' (onde este script já está rodando).
    Se 'ws' for fornecido, transmite o output em tempo real para o WebSocket.
    Retorna (success: bool, output: str)
    """
    full_output = ""
    try:
        full_command = ["python"] + command

        env = os.environ.copy()
        for key, value in env_vars.items():
            env[key] = value

        log_message = f"   (executando dentro do container: `{' '.join(full_command)}`)"
        print(log_message)
        if ws:
            await ws.send_str(log_message)

        process = await asyncio.create_subprocess_exec(
            *full_command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env
        )

        # Stream stdout
        async for line in process.stdout:
            decoded_line = line.decode('utf-8', errors='replace').strip()
            if decoded_line:
                print(decoded_line)
                full_output += decoded_line + "\n"
                if ws:
                    print(f"[WS SEND] {decoded_line}") # Debug print
                    await ws.send_str(decoded_line)

        # Stream stderr (if any remaining after stdout is exhausted)
        async for line in process.stderr:
            decoded_line = line.decode('utf-8', errors='replace').strip()
            if decoded_line:
                print(f"[STDERR] {decoded_line}")
                full_output += f"[STDERR] {decoded_line}\n"
                if ws:
                    print(f"[WS SEND] [STDERR] {decoded_line}") # Debug print
                    await ws.send_str(f"[STDERR] {decoded_line}")

        returncode = await process.wait()

        if returncode != 0:
            error_message = f"\n❌ Comando falhou com código de saída: {returncode}"
            print(error_message)
            full_output += error_message + "\n"
            if ws:
                await ws.send_str(error_message)
            return False, full_output
        
        success_message = f"\n✅ Comando concluído com sucesso."
        print(success_message)
        full_output += success_message + "\n"
        if ws:
            print(f"[WS SEND] {success_message}") # Debug print
            await ws.send_str(success_message)

        return True, full_output

    except Exception as e:
        error_message = f"❌ Ocorreu um erro ao executar o comando no container: {e}"
        print(error_message)
        full_output += error_message + "\n"
        if ws:
            print(f"[WS SEND] {error_message}") # Debug print
            await ws.send_str(error_message)
        import traceback
        traceback.print_exc()
        return False, str(e)