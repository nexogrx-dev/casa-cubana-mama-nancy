# HANDOFF TO CLAUDE

> Este documento explica a Claude cómo construir la web de Casa Cubana Mamá Nancy.
> Leer primero MASTER_CONTEXT.md antes de generar cualquier código.

---

## Source of Truth

```
MASTER_CONTEXT.md
```

Todos los textos, datos operativos, carta y filosofía del proyecto están consolidados en ese archivo. No inventar datos. No añadir secciones no documentadas.

---

## Project Overview

Casa Cubana Mamá Nancy es un pequeño bar cubano en el centro de Granada (Calle Duquesa 31). No es un restaurante formal. Es un espacio íntimo de convivencia: coctelería cubana, cocina casera y calor humano.

La propietaria es Nancy, cubana, que empezó cocinando desde la ventana de su casa en La Habana. Ese espíritu de casa abierta define toda la identidad del proyecto.

**Frase central del proyecto:**
> "Mi negocio es la convivencia. Transmitir el calor humano y el amor a la vida."

---

## Website Goal

Página de presentación de una sola página (one-page scroll).

Objetivos concretos:
- Presentar el lugar y su ambiente
- Mostrar bebidas y cocina
- Transmitir la historia y la filosofía de Nancy
- Facilitar el contacto directo (teléfono, WhatsApp, Instagram)

No es un e-commerce. No hay reservas online. No hay blog. Es una web de presencia simple, directa y con personalidad.

---

## Website Structure

La web es una sola página con scroll vertical. Orden de secciones:

### 1. Hero

**Título:** Casa Cubana Mamá Nancy
**Subtítulo:** Coctelería cubana, comida casera y calor humano en Granada.
**CTA:** botón de contacto directo (WhatsApp o teléfono)

Sin imagen de fondo por defecto — usar color de la paleta. Si hay foto disponible del local, usarla como fondo con overlay oscuro.

---

### 2. La casa

Texto corto que explica qué es el lugar.

> "Casa Cubana Mamá Nancy es un pequeño bar cubano donde la comida, las bebidas y la conversación forman parte de la misma experiencia. No es un restaurante formal. Es más bien una casa abierta donde las personas pueden reunirse, beber algo, comer con calma y pasar tiempo juntas."

Sin titular visible. El texto habla solo.

---

### 3. Bebidas

**Titular de sección:** Bebidas

6 bebidas con nombre y descripción corta. Fuente: `MASTER_CONTEXT.md > ## Bebidas`.

| Bebida | Tagline |
|---|---|
| Mojito Mamá Nancy | Pa' alegrarte la vida. |
| Piña Colada | Una pasada. |
| La Polla de Obama | Pa' los más atrevidos. |
| Morir Soñando | Sabor que embelesa. |
| Guasaco | Pa' que te pongas guapo o guapa. |
| Sangría | Pa' que te rías. |

Layout: grid de 2 columnas en mobile, 3 en desktop. Tarjetas simples: nombre + tagline. Sin precios (pendientes).

---

### 4. Cocina

**Titular de sección:** Cocina

7 platos con nombre y descripción breve. Fuente: `MASTER_CONTEXT.md > ## Cocina`.

Nota visible: *"La carta puede variar según el momento y la disponibilidad."*

Layout: lista vertical limpia o grid de 2 columnas.

---

### 5. Historia

**Titular de sección:** La historia de Mamá Nancy

Texto narrativo en primera persona. Fuente: `02_story/historia.md`.

Resumen para la web:

> "Mi historia empieza en La Habana. Durante mucho tiempo cociné desde la ventana de mi casa para vecinos y amigos. Poco a poco aquella ventana se convirtió en un pequeño lugar de encuentro. Con el tiempo la vida me llevó a Granada. Aquí intento mantener el mismo espíritu de casa abierta con el que todo empezó."

Esta sección debe sentirse íntima. Tipografía grande, texto centrado, fondo de color suave.

---

### 6. Contacto

**Titular de sección:** ¿Cómo encontrarnos?

Datos operativos. Fuente: `MASTER_CONTEXT.md > ## Datos operativos`.

```
Calle Duquesa 31, Centro
18001 Granada, España

Teléfono / WhatsApp: +34 634 08 07 99
Instagram: @cafebarmamanancy
```

**Nota de horarios:**
> "No funcionamos con horarios rígidos. Las aperturas pueden variar según el momento y las reservas. Para saber si estamos abiertos, consulta directamente."

CTA principal: botón de WhatsApp (`https://wa.me/34634080799`)
CTA secundario: enlace a Instagram (`https://www.instagram.com/cafebarmamanancy/`)

---

## Content Sources

| Contenido | Archivo fuente |
|---|---|
| Textos hero, la casa, filosofía, contacto | `05_web/textos_web.md` |
| Historia de Nancy | `02_story/historia.md` |
| Filosofía y principios | `02_story/filosofia.md` |
| Carta de bebidas | `03_menu/bebidas.md` |
| Carta de cocina | `03_menu/carta_base.md` |
| Datos operativos y contacto | `MASTER_CONTEXT.md` |

---

## Visual Direction

### Sensación general

Humana · Artesanal · Cálida · Tropical · Nunca corporativa.

El diseño debe parecer hecho con carácter, no con una plantilla genérica.

### Paleta de colores

```css
/* Principales */
--color-turquesa:    #3ABFBF;  /* turquesa caribeño */
--color-verde-menta: #7EC8A0;  /* verde menta */
--color-coral:       #E8714A;  /* coral / naranja atardecer */
--color-crema:       #F5EDD6;  /* crema cálido — fondo base */

/* Secundarios */
--color-verde-prof:  #2D6B4F;  /* verde tropical profundo */
--color-amarillo:    #F0C040;  /* amarillo cálido */
--color-rojo-coral:  #C94040;  /* rojo coral */
```

Fondo base de la web: `--color-crema`.
Texto principal: marrón oscuro o negro suave, nunca negro puro.

### Tipografía

**Titular / logo:** tipografía script o display de carácter artesanal.
Opciones de Google Fonts sin coste:
- `Pacifico` — script tropical, cálido
- `Lobster` — retro cubano
- `Playfair Display` — si se quiere algo más elegante

**Cuerpo de texto:** tipografía limpia y legible.
- `Lato`, `Inter` o `Source Sans 3`

Tamaño de cuerpo mínimo: 16px. Nunca tipografía fría ni geométrica fría.

### Estilo gráfico

- Ilustrado y ligeramente vintage
- Iconos de trazo artesanal (no flat genérico)
- Posibles elementos: vaso de mojito, hoja de menta, rodaja de lima, hojas tropicales
- Sin fotografías de stock genéricas de restaurante
- Separadores entre secciones: línea decorativa o patrón tropical sutil

---

## UX Requirements

- **Mobile-first.** Diseñar primero para pantalla de 375px.
- **Rápido.** Sin librerías pesadas. Sin animaciones CSS complejas. Sin JavaScript innecesario.
- **Texto corto.** Cada sección debe poder leerse en menos de 30 segundos.
- **CTA visible siempre.** El número de WhatsApp debe estar accesible desde cualquier punto de la página (sticky en móvil si es posible).
- **Sin formularios.** El contacto es directo: WhatsApp o Instagram.
- **Sin JavaScript de terceros** salvo lo estrictamente necesario (Google Analytics opcional, solo si se pide).
- **Accesible.** Contraste suficiente entre texto y fondo. Semántica HTML correcta.

---

## Expected Output

Claude debe generar los siguientes archivos:

### Estructura del proyecto

```
/web
  index.html
  /css
    styles.css
  /js
    main.js        ← mínimo, solo si hace falta
  /assets
    /fonts         ← si se usan fuentes locales
    /icons         ← iconos SVG del proyecto
    /images        ← placeholder, reemplazar con fotos reales
```

### Componentes principales

| Componente | Descripción |
|---|---|
| `<header>` | Nombre del bar + nav anchor links |
| `#hero` | Título, subtítulo, CTA WhatsApp |
| `#la-casa` | Párrafo de presentación del lugar |
| `#bebidas` | Grid de 6 bebidas con nombre y tagline |
| `#cocina` | Lista o grid de 7 platos |
| `#historia` | Texto narrativo de Nancy |
| `#contacto` | Dirección, teléfono, Instagram, nota de horarios |
| `<footer>` | Nombre + Instagram + copyright mínimo |

### Layout

- Una sola columna en mobile
- Máximo 2–3 columnas en desktop (grid CSS nativo, sin frameworks)
- Sin barra de navegación fija compleja — un anchor menu simple es suficiente
- Ancho máximo del contenido: 900px centrado

### Checklist de deploy

- [ ] HTML válido (sin errores en W3C validator)
- [ ] Meta tags básicos: `title`, `description`, `og:image`, `og:title`
- [ ] Favicon configurado
- [ ] Número de WhatsApp con enlace `wa.me` correcto
- [ ] Enlace de Instagram correcto
- [ ] Dirección con enlace a Google Maps (coordenadas: `37.1786553,-3.6031193`)
- [ ] Tipografías cargando correctamente
- [ ] Contraste de color accesible (WCAG AA mínimo)
- [ ] Imágenes con atributo `alt`
- [ ] Página probada en mobile (375px) y desktop (1280px)
- [ ] Página probada en Safari, Chrome y Firefox

---

## Notas finales para Claude

1. **No inventar datos.** Si falta información (precios, horarios exactos, fotos), dejar placeholder claro: `[PENDIENTE]` o usar texto genérico que no confunda al usuario final.
2. **Respetar el tono.** El proyecto habla en primera persona con calidez. Los textos del hero y de la sección Historia deben sonar a Nancy, no a una agencia.
3. **Priorizar el contacto.** El objetivo principal de la web es que alguien que la vea pueda contactar con el bar en menos de 10 segundos.
4. **No añadir secciones no documentadas.** Si no está en MASTER_CONTEXT.md, no está en la web.
