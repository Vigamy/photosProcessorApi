import sys

try:
    import pygame
except Exception as exc:
    print(f"pygame unavailable: {exc}")
    sys.exit(0)


pygame.init()
screen = pygame.display.set_mode((640, 360))
pygame.display.set_caption("SpyWhere Game")
clock = pygame.time.Clock()
font = pygame.font.SysFont(None, 36)

running = True
while running:
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False

    screen.fill((20, 20, 30))
    text = font.render("SpyWhere game running", True, (220, 220, 220))
    screen.blit(text, (160, 160))
    pygame.display.flip()
    clock.tick(60)

pygame.quit()
