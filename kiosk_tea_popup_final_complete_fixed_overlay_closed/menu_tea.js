
document.addEventListener("DOMContentLoaded", function () {
  const menuButtons = document.querySelectorAll(".menu-item");
  const overlay = document.createElement("div");
  overlay.className = "overlay";
  document.body.appendChild(overlay);

  overlay.style.display = "none";

  menuButtons.forEach(button => {
    button.addEventListener("click", () => {
      const popup = document.querySelector("#tea-popup-template").content.cloneNode(true);
      overlay.innerHTML = "";
      overlay.appendChild(popup);
      overlay.style.display = "flex";

      overlay.querySelectorAll(".option-button").forEach(btn => {
        btn.addEventListener("click", () => {
          const group = btn.getAttribute("data-group");
          overlay.querySelectorAll(`.option-button[data-group='${group}']`).forEach(b => b.classList.remove("selected"));
          btn.classList.add("selected");
        });
      });

      overlay.querySelector(".complete-button").addEventListener("click", () => {
        const size = overlay.querySelector(".option-button[data-group='size'].selected")?.innerText;
        const hotice = overlay.querySelector(".option-button[data-group='hotice'].selected")?.innerText;
        if (!size || !hotice) {
          alert("모든 옵션을 선택해 주세요.");
          return;
        }

        const cart = document.querySelector(".cart-items");
        const newItem = document.createElement("div");
        newItem.innerHTML = `
          <div style="min-width: 300px; border-right: 2px solid #ccc; padding: 20px; text-align: center;">
            <img src="images/캐모마일.png" style="height: 150px;" />
            <div style="font-size: 36px; margin-top: 10px;">차<br><span style="font-size: 34px;">${hotice} / ${size}</span></div>
          </div>
        `;
        cart.appendChild(newItem);

        overlay.style.display = "none";
      });
    });
  });
});


// Fix to close the tea popup overlay
document.addEventListener("DOMContentLoaded", function () {
  const overlay = document.querySelector(".overlay");
  const completeButton = document.querySelector(".complete-button");

  if (completeButton && overlay) {
    completeButton.addEventListener("click", () => {
      const size = document.querySelector(".option-button[data-group='size'].selected")?.innerText;
      const hotice = document.querySelector(".option-button[data-group='hotice'].selected")?.innerText;

      if (!size || !hotice) {
        alert("모든 옵션을 선택해 주세요.");
        return;
      }

      // 장바구니 추가 생략

      // 팝업 닫기
      overlay.style.display = "none";
    });
  }
});
