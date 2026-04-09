import os

def load_business_context() -> str:
    '''
    Carga el archivo de contexto de negocio para inyectarlo en el prompt de la IA.
    '''
    filepath = os.path.join(
        os.path.dirname(__file__), 
        "conocimiento_empresa.md"
    )
    
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        return "Información general no disponible en este momento."
