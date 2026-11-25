// The scan mat page (mat.html): moved out of the page so the site's CSP can forbid inline script.
import { DIAGRAM_CSS, matDiagram } from "/assets/diagrams.js";
document.head.insertAdjacentHTML("beforeend", `<style>${DIAGRAM_CSS}</style>`);
document.getElementById("mat-diagram").innerHTML = matDiagram();
import("/assets/interact.js").then(({ assembleMat }) => assembleMat(document.getElementById("mat-diagram")));
