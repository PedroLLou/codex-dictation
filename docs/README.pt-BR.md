# Ditado Codex para Windows

Companheiro de ditado experimental para o T3 Code. Não é um recurso oficial do T3 nem da OpenAI. Usa o login ChatGPT já gerenciado pelo Codex; o serviço, a disponibilidade e a cota podem mudar.

Baixe o ZIP na [página de releases](https://github.com/PedroLLou/codex-dictation/releases/latest), extraia tudo e abra `Start Codex Dictation.vbs`. Não precisa instalar Python. Antes, entre no Codex CLI com sua conta ChatGPT (`codex login`). Não mova somente o executável.

Em Preferences, escolha o microfone e mude Language para Português. Salve, feche e reabra. O idioma da interface não traduz o que você dita.

Clique no microfone para gravar e clique novamente para parar. `Ctrl+Alt+Space` inicia/para; `Esc` cancela. Para inserir diretamente, ative Inserir no campo, deixe o cursor no campo e use o atalho. A inserção só acontece se o campo original ainda puder ser verificado e continuar focado; o aplicativo não envia Enter.

O mini aparece somente com o T3 ativo e some ao trocar de aplicativo. Nele, a inserção no campo original é automática. Se o foco mudar, o texto fica no editor para revisão. A barrinha rosa indica falta de conexão. O microfone não abre sozinho. Se você trocar de aplicativo durante uma gravação, ela continua até ser parada/cancelada pelo atalho.

As preferências também permitem criar um atalho na área de trabalho e habilitar Iniciar com o Windows. A inicialização automática vem desligada e é feita somente para seu usuário. Para removê-la, desmarque a opção antes de apagar/mover a pasta.

Áudio e histórico ficam em RAM e desaparecem ao encerrar. Áudio vai para o serviço remoto do Codex. O app descarta respostas de voz/texto do assistente. Transcrições incompletas não são inseridas automaticamente; recuperação deve ser solicitada. Há histórico da sessão, exportação manual e dicionário opcional de substituições.

Código, instruções de compilação, testes e limitações: [README em inglês](../README.md). Windows 10 x64 foi testado; a release não possui assinatura digital. Os checksums SHA-256 acompanham o download.
