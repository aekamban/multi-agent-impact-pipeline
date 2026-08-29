with open('rag_ingestion.py', 'r') as f:
    content = f.read()

old = '    vectorstore = FAISS.from_documents(all_docs, embeddings)'
new = '''    import time
    batch_size = 100
    vectorstore = None
    total_batches = (len(all_docs) - 1) // batch_size + 1
    for i in range(0, len(all_docs), batch_size):
        batch = all_docs[i:i + batch_size]
        batch_num = i // batch_size + 1
        print(f"  Embedding batch {batch_num}/{total_batches} ({len(batch)} chunks)...")
        if vectorstore is None:
            vectorstore = FAISS.from_documents(batch, embeddings)
        else:
            vectorstore.add_documents(batch)
        if i + batch_size < len(all_docs):
            time.sleep(15)'''

if old in content:
    with open('rag_ingestion.py', 'w') as f:
        f.write(content.replace(old, new))
    print("SUCCESS")
else:
    print("ERROR - not found")
