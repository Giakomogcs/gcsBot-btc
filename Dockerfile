# Dockerfile (VERSÃO OTIMIZADA COM MULTI-STAGE)

# --- ESTÁGIO 1: Build ---
# Usamos uma imagem completa para compilar dependências que possam precisar de ferramentas de build
FROM python:3.12-slim as builder

# Instala dependências de sistema necessárias para compilar pacotes Python [cite: 3]
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libgomp1 && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Instala as dependências Python em um ambiente virtual isolado
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements-core.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements-core.txt

# --- ESTÁGIO 2: Final ---
# Usamos a imagem slim, que é leve, para a imagem final
FROM python:3.12-slim as final

# Instala apenas a dependência de sistema necessária para rodar o LightGBM [cite: 3]
RUN apt-get update && \
    apt-get install -y --no-install-recommends libgomp1 && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copia o ambiente virtual com as dependências já instaladas do estágio de build
COPY --from=builder /opt/venv /opt/venv

# Copia o código da sua aplicação [cite: 5]
COPY . .

# Copia o script wait-for-it
ADD https://raw.githubusercontent.com/vishnubob/wait-for-it/master/wait-for-it.sh /
RUN chmod +x /wait-for-it.sh

# Define o PATH para usar o Python do ambiente virtual
ENV PATH="/opt/venv/bin:$PATH"

# Comando para iniciar a aplicação, agora usando o ambiente virtual
CMD ["/wait-for-it.sh", "db:8086", "--", "python", "-u", "main.py"]