# Third-party software and generated records

The MIT license in `LICENSE` covers this project's original source code, documentation, and hand-authored input/expected-answer fixtures. It does not relicense Apple software, models, model-generated text, or linked third-party projects.

## Apple Python SDK

Dependency: `apple-fm-sdk==0.2.1`, Copyright (C) 2026 Apple Inc. All Rights Reserved. License: Apache-2.0. The unmodified license is preserved in [licenses/apple-fm-sdk-0.2.1-LICENSE.md](licenses/apple-fm-sdk-0.2.1-LICENSE.md). [Official release source](https://github.com/apple/python-apple-fm-sdk/tree/v0.2.1).

The SDK is installed from its package distribution, not vendored here. No SDK source or binary has been copied into this repository, and installed SDK code is not modified. The streaming helper uses its public API. This dependency's license is distinct from the OS-managed AFM model's terms.

## Apple OS, framework and model

macOS, FoundationModels.framework, `fm`, and AFM assets are supplied by Apple and are not redistributed here. Running the test app remains subject to applicable Apple agreements and [FoundationModels acceptable use requirements](https://developer.apple.com/support/terms/acceptable-use-requirements-for-the-foundation-models-framework/). This repository does not grant rights to modify or redistribute the model.

## Model-generated records

`results/` includes AI-generated text clearly labelled by its result fields and documented in [results/README.md](results/README.md). MIT does not grant additional rights to that text. The measured host's macOS software license, section 6.E, prohibits using AI output to train, fine-tune, or improve another AI model. These outputs are published as evaluation evidence, not as a model-training dataset.

Apple states that it does not claim ownership of AI outputs, subject to pre-existing Apple or third-party rights. This is not an assurance that every output is copyrightable, original, or free of third-party rights. [Apple software license agreements](https://www.apple.com/legal/sla/).

## Research links

The international case catalogue links to primary sources. Their code, assets, and licenses are not incorporated or relicensed by this project. This is an independent study, with no endorsement by Apple or the referenced projects.
