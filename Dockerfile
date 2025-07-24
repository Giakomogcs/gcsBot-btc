# Dockerfile (VERSÃO CORRIGIDA)
# Substitua o conteúdo do seu Dockerfile por este.

# Usa uma imagem base oficial do Python, leve e otimizada
FROM python:3.12-slim

# Instala a dependência de sistema 'libgomp1' que é necessária para o LightGBM.
RUN apt-get update && \
    apt-get install -y --no-install-recommends libgomp1 && \
    rm -rf /var/lib/apt/lists/*

# Define o diretório de trabalho dentro do container
WORKDIR /app

# Copia o arquivo de dependências primeiro para aproveitar o cache do Docker
COPY requirements.txt .

# Instala as dependências Python
RUN pip install --no-cache-dir -r requirements.txt

# Copia todo o resto do código do seu projeto para dentro do container
COPY . .

# Adiciona o script wait-for-it e o torna executável
ADD https://raw.githubusercontent.com/vishnubob/wait-for-it/master/wait-for-it.sh /
RUN chmod +x /wait-for-it.sh

# O CMD agora espera pelo serviço 'db' na porta do InfluxDB (8086)
CMD ["/wait-for-it.sh", "db:8086", "--", "python", "-u", "main.py"]