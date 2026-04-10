import os
from datetime import datetime
from typing import List

from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from dotenv import load_dotenv

# Carrega as variáveis de ambiente
load_dotenv()

# Configuração do banco de dados
# O Railway fornece MYSQL_URL, mas o SQLAlchemy precisa de mysql+pymysql://
DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("MYSQL_URL") or "sqlite:///./test.db"

if DATABASE_URL.startswith("mysql://"):
    DATABASE_URL = DATABASE_URL.replace("mysql://", "mysql+pymysql://", 1)

print(f"Configurando banco de dados...")

# Configura a engine com pool_pre_ping para evitar conexões mortas no Railway
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# --- Modelos ---
class ConsultaCashback(Base):
    __tablename__ = "consultas_cashback"
    id = Column(Integer, primary_key=True, index=True)
    ip_usuario = Column(String(50), index=True)
    nome = Column(String(100))
    tipo_cliente = Column(String(50))
    valor = Column(Float)
    cashback = Column(Float)
    criado_em = Column(DateTime, default=datetime.utcnow)

# --- Esquemas ---
class CalcularRequest(BaseModel):
    nome: str
    tipo_cliente: str
    valor: float

class CalcularResponse(BaseModel):
    cashback: float

# --- App FastAPI ---
app = FastAPI(title="Cashback API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# --- Eventos de Ciclo de Vida ---
@app.on_event("startup")
def startup_event():
    print("Iniciando aplicação e verificando banco de dados...")
    try:
        Base.metadata.create_all(bind=engine)
        print("Banco de dados pronto para uso.")
    except Exception as e:
        print(f"AVISO: Falha ao conectar no banco MySQL. Usando modo degradado. Erro: {e}")

# --- Rotas ---

@app.get("/health")
def health_check():
    return {"status": "ok", "db_url_type": DATABASE_URL.split(":")[0]}

@app.get("/")
def serve_frontend():
    if os.path.exists("index.html"):
        return FileResponse("index.html")
    return {"error": "Arquivo index.html não encontrado no servidor."}

@app.post("/calcular", response_model=CalcularResponse)
def calcular_cashback(req_data: CalcularRequest, request: Request, db: Session = Depends(get_db)):
    # Captura de IP (considerando headers do Railway)
    ip = request.client.host
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        ip = forwarded_for.split(",")[0].strip()

    taxa = 0.10 if req_data.tipo_cliente.lower() == "vip" else 0.05
    valor_cashback = req_data.valor * taxa
    
    nova_consulta = ConsultaCashback(
        ip_usuario=ip,
        nome=req_data.nome,
        tipo_cliente=req_data.tipo_cliente.upper(),
        valor=req_data.valor,
        cashback=valor_cashback
    )
    
    try:
        db.add(nova_consulta)
        db.commit()
    except Exception as e:
        db.rollback()
        # Se falhar o banco, ainda retornamos o cálculo para não quebrar a UX
        print(f"Erro ao salvar consulta: {e}")
        return CalcularResponse(cashback=valor_cashback)

    return CalcularResponse(cashback=valor_cashback)

@app.get("/historico")
def obter_historico(request: Request, db: Session = Depends(get_db)):
    ip = request.client.host
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        ip = forwarded_for.split(",")[0].strip()
        
    try:
        consultas = db.query(ConsultaCashback).filter(ConsultaCashback.ip_usuario == ip).order_by(ConsultaCashback.criado_em.desc()).all()
        resultado = [{
            "tipo_cliente": c.tipo_cliente,
            "valor": c.valor,
            "cashback": c.cashback,
            "criado_em": c.criado_em.isoformat()
        } for c in consultas]
        return {"historico": resultado}
    except Exception as e:
        print(f"Erro ao buscar histórico: {e}")
        return {"historico": [], "error": "Banco de dados indisponível"}
