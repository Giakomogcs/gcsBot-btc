# Usa uma imagem base oficial do Python, leve e otimizada
FROM python:3.12-slim

# ### CORREÇÃO DEFINITIVA ###
# Instala a dependência de sistema 'libgomp1' que é necessária para o LightGBM funcionar.
# - apt-get update: Atualiza a lista de pacotes disponíveis.
# - apt-get install -y libgomp1: Instala a biblioteca sem pedir confirmação.
# - --no-install-recommends: Evita instalar pacotes desnecessários.
# - rm -rf /var/lib/apt/lists/*: Limpa o cache para manter a imagem final pequena.
RUN apt-get update && \
    apt-get install -y --no-install-recommends libgomp1 postgresql-client && \
    rm -rf /var/lib/apt/lists/*

# Define o diretório de trabalho dentro do container
WORKDIR /app

# Copia o arquivo de dependências primeiro para aproveitar o cache do Docker
COPY requirements.txt .

# Instala as dependências Python
RUN pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org --no-cache-dir -r requirements.txt

# Copia todo o resto do código do seu projeto para dentro do container
COPY . .

# Adiciona o script wait-for-it e o torna executável
ADD https://raw.githubusercontent.com/vishnubob/wait-for-it/master/wait-for-it.sh /
RUN chmod +x /wait-for-it.sh

# O -u garante que a saída do Python apareça nos logs do Docker em tempo real
CMD ["/wait-for-it.sh", "db:5432", "--", "python", "-u", "main.py"]