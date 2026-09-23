import re
RULES=[
("PRICE","HIGH",[r"\bpreço\b",r"\bvalor\b",r"R\$\s*\d"]),
("BUDGET","HIGH",[r"\borçamento\b"]),("PAYMENT","HIGH",[r"\bpagamento\b",r"\bpagar\b",r"\bPIX\b"]),
("DEADLINE_CHANGE","HIGH",[r"\badiar\b",r"\bprorrogar\b",r"\balterar o prazo\b"]),
("SCOPE_CHANGE","HIGH",[r"\balterar o escopo\b"]),("CONTRACT","CRITICAL",[r"\bcontrato\b",r"\bassinar\b"]),
("TECHNICAL_RESPONSIBILITY","CRITICAL",[r"\bresponsabilidade técnica\b",r"\bART\b",r"\bRRT\b"]),
("SAFETY","CRITICAL",[r"\bsegurança\b",r"\bacidente\b"]),("LEGAL","CRITICAL",[r"\bjurídic[oa]\b"])
]
def scan(content:str):
    flags=[]
    for code,severity,patterns in RULES:
        for pat in patterns:
            m=re.search(pat,content,re.I)
            if m:
                flags.append({"code":code,"severity":severity,"evidence":m.group(0),"approval_required":True});break
    rank={"LOW":1,"MEDIUM":2,"HIGH":3,"CRITICAL":4}
    level=max((x["severity"] for x in flags),key=lambda x:rank[x],default="LOW")
    return {"risk_level":level,"flags":flags,"unsupported_claims":[],"missing_information":[],
            "sensitive_data_detected":[],"recommended_action":"human_review" if flags else "continue"}
