# FlashForge — Constructor de Mazos PAU

## Qué es

Add-on para Anki 25.09 que permite crear mazos de flashcards de forma rápida
con múltiples tipos de tarjetas y optimización FSRS para exámenes PAU.

## Instalación

1. Copia la carpeta `1742078545` al directorio de addons de Anki:
   `~/.local/share/Anki2/addons21/`
2. Reinicia Anki
3. Ve a **Herramientas → FlashForge — Constructor de Mazos PAU**

## Tipos de Tarjeta Soportados

| # | Tipo | Uso |
|---|------|-----|
| 1 | Básico (Pregunta → Respuesta) | Definiciones, hechos, vocabulario básico |
| 2 | Básico con Imagen | Preguntas visuales con imagen de soporte |
| 3 | Inverso (Respuesta → Pregunta) | Auto-genera la tarjeta inversa |
| 4 | Pregunta Abierta | Sin respuesta fija — para práctica libre |
| 5 | Cloze (Texto con huecos) | `[[hueco]]` en cualquier texto |
| 6 | Dos Caras (Término + Definición) | Vocabulario, conceptos con ejemplo |

## FSRS — Optimización para PAU

FSRS (Free Spaced Repetition Scheduler) calcula automáticamente los
intervalos de repaso óptimos para que el día del examen tengas máxima retención.

### Estrategia de intervalos (antes del examen)

```
Fase 1: Repaso amplio     → 30 días antes
Fase 2: Consolidación     → 14 días antes
Fase 3: Repaso medio      →  7 días antes
Fase 4: Repaso intensivo   →  3 días antes
Fase 5: Cram final        →  1 día antes
```

### Configuración recomendada PAU

- **Retención**: 90%
- **Nuevas tarjetas/día**: 30
- **Revisiones/día**: 200

## Importación JSON

El add-on lee archivos JSON con el formato:

```json
{
  "deck": "Nombre del Mazo",
  "exam_date": "2026-06-15",
  "cards": [
    {"front": "¿Qué es X?", "back": "Respuesta", "tags": ["tag1"]},
    {"front": "¿Qué es Y?", "back": "Respuesta", "tags": ["tag2"]},
    {"text": "Texto con [[hueco]] para cloze", "tags": ["cloze"]},
    {"term": "Mitosis", "def": "División celular", "example": "2 células"}
  ]
}
```

**Mapeo por tipo de tarjeta:**

| Tipo | Campo 1 | Campo 2 | Campo 3 |
|------|---------|---------|---------|
| Básico | `front` → Pregunta | `back` → Respuesta | — |
| Cloze | `text` → Texto con `[[hueco]]` | — | — |
| Dos Caras | `term` → Término | `def` → Definición | `example` → Ejemplo |

## Añadir Tarjetas en Bloque

Pega datos desde una tabla (Excel, Google Sheets) usando **TAB** como
separador de columnas. El add-on detecta automáticamente el tipo de tarjeta
según el nombre del mazo.

## Workflow PAU Recomendado

1. **Crear mazo** → Define nombre, tipo de tarjeta, fecha del examen
2. **Importar JSON** → Carga tus tarjetas desde archivos externos
3. **FSRS Config** → Calcula y aplica los intervalos óptimos
4. **Añadir más tarjetas** → Usa la pestaña de bulk-add para pegar desde表格

## Archivos

```
1742078545/
  flashforge.py       — Módulo principal
  manifest.json       — Metadatos del add-on
```

```
Ejemplo_Biologia_Genetica.json  — Deck de ejemplo con 16 tarjetas de biología
```

## Requisitos

- Anki 25.09+
- Python 3.13+ (incluido en Anki)
- PyQt6 (incluido en Anki)

## Autor

rgodim — built for PAU success 🧠