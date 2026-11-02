import os
from ..config import KNOWLEDGE_DIR,CHROMA_DIR
os.environ["HF_ENDPOINT"]="https://hf-mirror.com"
os.environ["HF_HUB_OFFLINE"]="1"
os.environ["TRANSFORMERS_OFFLINE"]="1"

def load_knowledge()->list[dict]:
    chunks=[]
    base=os.path.join(KNOWLEDGE_DIR)
    for filename in os.listdir(base):
        if not filename.endswith(".txt"):
            continue
        with open(os.path.join(base,filename),"r",encoding="utf-8") as f:
            for line in f:
                line=line.strip()
                if  line:
                    chunks.append({"source":filename,"text":line})

    return chunks

import chromadb
from sentence_transformers import SentenceTransformer

model=SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
client=chromadb.PersistentClient(path=CHROMA_DIR)
collection=client.get_or_create_collection("knowledge")

def index_knowledge():
    if collection.count()>0:
        return

    chunks=load_knowledge()
    texts=[c["text"]for c in chunks]
    embeddings=model.encode(texts).tolist()
    collection.add(
        documents=texts,
        embeddings=embeddings,
        metadatas=[{"source":c["source"]}for c in chunks],
        ids=[f"{c['source']}_{i}"for i,c in enumerate(chunks)]
    )

def retrieve(query:str,recall_k:int=10)->list[dict]:
    q_vec=model.encode(query).tolist()
    results=collection.query(
        query_embeddings=[q_vec],
        n_results=recall_k,
    )
    candidates=[]
    for doc,meta in zip(results["documents"][0],results["metadatas"][0]):
        candidates.append({"text":doc,"source":meta["source"]})

    return candidates

from sentence_transformers import CrossEncoder


reranker=CrossEncoder("BAAI/bge-reranker-base")

def rerank(query:str,candidates:list[dict],top_k:int)->list[dict]:
    if not candidates:
        return []
    pairs=[(query,c["text"])for c in candidates]
    scores=reranker.predict(pairs)
    ranked=sorted(zip(candidates,scores),key=lambda x:x[1],reverse=True)
    return [c for c,_ in ranked[:top_k]]

def search_knowledge(query:str,recall_k:int=10,top_k:int=3)->str:
    candidates=retrieve(query,recall_k)
    reranked=rerank(query,candidates,top_k)
    return "\n".join(f"[{c['source']}]{c['text']}"for c in reranked[:top_k])

index_knowledge()