document.addEventListener('DOMContentLoaded', function() {
    document.querySelectorAll('.menu-checkbox input').forEach(checkbox => {
      checkbox.addEventListener('change', function() {
        const menuLink = this.closest('.menu-link');
        if (this.checked) {
          menuLink.classList.add('active');
        } else {
          menuLink.classList.remove('active');
        }
      });
    });

    document.querySelector('.menu-link.active').addEventListener('click', function(e) {
      e.preventDefault();
    });

    const checkedItems = ['Orders'];
    document.querySelectorAll('.menu-link').forEach(link => {
      if (checkedItems.includes(link.querySelector('span').textContent)) {
        const checkbox = link.querySelector('input');
        if (checkbox) {
          checkbox.checked = true;
          link.classList.add('active');
        }
      }
    });
  });